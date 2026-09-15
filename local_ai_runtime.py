"""Robust local AI runtime for the Windows desktop application.

Priority on Windows:
1. Reuse an already running Ollama model (prefer qwen3:4b).
2. Reuse an already running LM Studio OpenAI server with a Qwen3 4B model.
3. If qwen3:4b is installed in Ollama but the service is stopped, start Ollama.
4. Load an existing Qwen3 4B GGUF from LM Studio with bundled llama.cpp.
5. Last resort: let bundled llama.cpp download the configured Qwen3 4B GGUF.
"""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Callable, Optional

import requests


ProgressCallback = Optional[Callable[[str], None]]
API_MODEL_ALIAS = "binance-square-local"
_MIN_MODEL_BYTES = 100 * 1024 * 1024
_OLLAMA_URL = "http://127.0.0.1:11434"
_LMSTUDIO_URL = "http://127.0.0.1:1234"


def _progress(callback: ProgressCallback, message: str) -> None:
    if callback is not None:
        try:
            callback(message)
        except Exception:
            pass


def _human_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if size < 1024.0 or unit == "ТБ":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} ТБ"


def app_data_dir() -> Path:
    root = os.getenv("LOCALAPPDATA") if os.name == "nt" else None
    base = Path(root) if root else Path.home() / ".local" / "share"
    path = base / "BinanceSquareBot"
    path.mkdir(parents=True, exist_ok=True)
    return path


def bundle_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(getattr(sys, "_MEIPASS"))
    return Path(__file__).resolve().parent


def find_llama_server() -> Optional[Path]:
    explicit = (os.getenv("LLAMA_SERVER_PATH") or "").strip().strip('"')
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    candidates = [
        bundle_dir() / "llama" / "llama-server.exe",
        bundle_dir() / "llama" / "llama-server",
        Path.cwd() / "llama" / "llama-server.exe",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for name in ("llama-server.exe", "llama-server", "llama"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def find_ollama() -> Optional[Path]:
    explicit = (os.getenv("OLLAMA_EXE") or "").strip().strip('"')
    if explicit and Path(explicit).is_file():
        return Path(explicit)
    found = shutil.which("ollama.exe") or shutil.which("ollama")
    if found:
        return Path(found)
    local = os.getenv("LOCALAPPDATA")
    if local:
        for candidate in (
            Path(local) / "Programs" / "Ollama" / "ollama.exe",
            Path(local) / "Ollama" / "ollama.exe",
        ):
            if candidate.is_file():
                return candidate
    return None


def _model_text(path: Path) -> str:
    try:
        return str(path).lower().replace("_", "-")
    except Exception:
        return path.name.lower().replace("_", "-")


def _score_model(path: Path) -> int:
    text = _model_text(path)
    score = 0
    if "qwen" in text:
        score += 1000
    if "qwen3" in text:
        score += 700
    if any(token in text for token in ("4b", "4-b", "4.0b")):
        score += 900
    elif any(token in text for token in ("8b", "9b", "7b")):
        score += 100
    if "q4-k-m" in text or "q4_k_m" in text:
        score += 300
    elif "q5-k-m" in text or "q5_k_m" in text:
        score += 220
    elif "q4" in text:
        score += 160
    try:
        size = path.stat().st_size
        if 1 * 1024**3 <= size <= 4 * 1024**3:
            score += 150
        elif size > 1024**3:
            score += 60
    except OSError:
        pass
    return score


def find_installed_gguf(progress: ProgressCallback = None) -> Optional[Path]:
    explicit = (os.getenv("LOCAL_AI_MODEL_PATH") or "").strip().strip('"')
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file() and path.suffix.lower() == ".gguf":
            return path

    if os.getenv("LOCAL_AI_PREFER_INSTALLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
        return None

    home = Path.home()
    roots = [home / ".lmstudio" / "models"]
    extra = (os.getenv("LMSTUDIO_MODELS_DIR") or "").strip().strip('"')
    if extra:
        roots.insert(0, Path(extra).expanduser())

    candidates: list[Path] = []
    for root in roots:
        if not root.is_dir():
            continue
        _progress(progress, f"Ищу Qwen3 4B GGUF в {root}…")
        try:
            for path in root.rglob("*.gguf"):
                try:
                    if path.is_file() and path.stat().st_size >= _MIN_MODEL_BYTES:
                        candidates.append(path)
                except OSError:
                    continue
        except OSError:
            continue

    if not candidates:
        return None
    candidates.sort(key=lambda p: (_score_model(p), p.stat().st_size), reverse=True)
    best = candidates[0]
    if "qwen" not in _model_text(best):
        return None
    return best


def _ollama_model_from_tags(data: object) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    models = data.get("models")
    if not isinstance(models, list):
        return None
    names: list[str] = []
    for row in models:
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("model") or "").strip()
        if name:
            names.append(name)
    for name in names:
        low = name.lower()
        if low == "qwen3:4b" or ("qwen3" in low and "4b" in low):
            return name
    for name in names:
        if "qwen3" in name.lower():
            return name
    return None


def _probe_ollama(timeout: float = 1.2) -> Optional[str]:
    try:
        response = requests.get(_OLLAMA_URL + "/api/tags", timeout=timeout)
        if response.ok:
            return _ollama_model_from_tags(response.json())
    except (requests.RequestException, ValueError):
        pass
    return None


def _probe_lmstudio(timeout: float = 1.2) -> Optional[str]:
    try:
        response = requests.get(_LMSTUDIO_URL + "/v1/models", timeout=timeout)
        if not response.ok:
            return None
        data = response.json()
    except (requests.RequestException, ValueError):
        return None
    rows = data.get("data") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        return None
    names = [str(row.get("id") or "").strip() for row in rows if isinstance(row, dict)]
    for name in names:
        low = name.lower()
        if "qwen3" in low and "4b" in low:
            return name
    for name in names:
        if "qwen3" in name.lower():
            return name
    return None


def _ollama_manifest_exists() -> bool:
    roots: list[Path] = []
    env_root = (os.getenv("OLLAMA_MODELS") or "").strip().strip('"')
    if env_root:
        roots.append(Path(env_root).expanduser())
    roots.append(Path.home() / ".ollama" / "models")
    for root in roots:
        manifests = root / "manifests"
        if not manifests.is_dir():
            continue
        try:
            for path in manifests.rglob("*"):
                if not path.is_file():
                    continue
                text = str(path).lower().replace("\\", "/")
                if "/qwen3/4b" in text or ("qwen3" in text and path.name.lower() == "4b"):
                    return True
        except OSError:
            continue
    return False


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class LocalAIServer:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.host = "127.0.0.1"
        self.port = int(os.getenv("LOCAL_AI_PORT", "8089"))
        self.log_handle = None
        self.model_path: Optional[Path] = None
        self.model_label = (os.getenv("LOCAL_AI_MODEL_NAME") or "Qwen3 4B").strip()
        self.api_model = (os.getenv("LOCAL_AI_API_MODEL") or API_MODEL_ALIAS).strip() or API_MODEL_ALIAS
        self.backend = "llama.cpp"
        self.managed = False
        self._start_lock = threading.Lock()
        self._last_log_report = ""

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def endpoint(self) -> str:
        return self.base_url + "/v1/chat/completions"

    def healthy(self, timeout: float = 1.5) -> bool:
        try:
            if self.backend == "ollama":
                response = requests.get(self.base_url + "/api/tags", timeout=timeout)
            elif self.backend == "lmstudio":
                response = requests.get(self.base_url + "/v1/models", timeout=timeout)
            else:
                response = requests.get(self.base_url + "/health", timeout=timeout)
            return 200 <= response.status_code < 300
        except requests.RequestException:
            return False

    def _export_env(self) -> None:
        # Normal keys are useful in the GUI process. Runtime keys are deliberately
        # separate so a worker re-reading desktop.env cannot overwrite discovered
        # Ollama/LM Studio routing or a dynamically chosen llama.cpp port.
        os.environ["LOCAL_AI_ENDPOINT"] = self.endpoint
        os.environ["LOCAL_AI_API_MODEL"] = self.api_model
        os.environ["LOCAL_AI_MODEL_NAME"] = self.model_label
        os.environ["LOCAL_AI_BACKEND"] = self.backend
        os.environ["LOCAL_AI_RUNTIME_ENDPOINT"] = self.endpoint
        os.environ["LOCAL_AI_RUNTIME_API_MODEL"] = self.api_model
        os.environ["LOCAL_AI_RUNTIME_MODEL_NAME"] = self.model_label
        os.environ["LOCAL_AI_RUNTIME_BACKEND"] = self.backend

    def _log_path(self) -> Path:
        name = "ollama-server.log" if self.backend == "ollama" else "llama-server.log"
        return app_data_dir() / "logs" / name

    def _log_tail(self, limit: int = 12) -> str:
        path = self._log_path()
        if not path.is_file():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-limit:])
        except OSError:
            return ""

    def _attach_running_backend(self, progress: ProgressCallback) -> bool:
        if os.getenv("LOCAL_AI_PREFER_INSTALLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
            return False

        ollama_model = _probe_ollama()
        if ollama_model:
            self.backend = "ollama"
            self.host = "127.0.0.1"
            self.port = 11434
            self.api_model = ollama_model
            self.model_label = ollama_model
            self.managed = False
            self._export_env()
            _progress(progress, f"Найден уже запущенный локальный Ollama: {ollama_model}. Использую его без повторной загрузки.")
            return True

        lm_model = _probe_lmstudio()
        if lm_model:
            self.backend = "lmstudio"
            self.host = "127.0.0.1"
            self.port = 1234
            self.api_model = lm_model
            self.model_label = lm_model
            self.managed = False
            self._export_env()
            _progress(progress, f"Найден запущенный локальный сервер LM Studio: {lm_model}. Использую его напрямую.")
            return True
        return False

    def _start_installed_ollama(self, progress: ProgressCallback) -> bool:
        if os.getenv("LOCAL_AI_PREFER_INSTALLED", "1").strip().lower() not in {"1", "true", "yes", "on"}:
            return False
        ollama = find_ollama()
        if ollama is None or not _ollama_manifest_exists():
            return False

        self.backend = "ollama"
        self.host = "127.0.0.1"
        self.port = 11434
        self.api_model = "qwen3:4b"
        self.model_label = "qwen3:4b"
        log_dir = app_data_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        self.log_handle = open(log_dir / "ollama-server.log", "w", encoding="utf-8", errors="replace")
        env = os.environ.copy()
        env["OLLAMA_HOST"] = "127.0.0.1:11434"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        try:
            self.process = subprocess.Popen(
                [str(ollama), "serve"],
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                env=env,
                creationflags=flags,
            )
        except OSError:
            self.process = None
            return False
        self.managed = True
        self._export_env()
        _progress(progress, "Нашёл установленный qwen3:4b в Ollama. Запускаю локальный Ollama-сервер…")
        return True

    def start(self, progress: ProgressCallback = None) -> None:
        with self._start_lock:
            if self.healthy():
                self._export_env()
                _progress(progress, f"Локальный ИИ уже запущен: {self.model_label}.")
                return
            if self.process is not None and self.process.poll() is None:
                _progress(progress, "Локальный сервер уже запускается — жду готовности модели.")
                return

            if self._attach_running_backend(progress):
                return
            if self._start_installed_ollama(progress):
                return

            server = find_llama_server()
            if server is None:
                raise FileNotFoundError("В сборке не найден llama-server.exe")

            self.backend = "llama.cpp"
            self.host = "127.0.0.1"
            self.port = int(os.getenv("LOCAL_AI_PORT", "8089"))
            self.api_model = API_MODEL_ALIAS
            self.model_path = find_installed_gguf(progress)
            hf_model = (os.getenv("LOCAL_AI_HF_MODEL") or "Qwen/Qwen3-4B-GGUF:Q4_K_M").strip()
            ctx = max(2048, min(int(os.getenv("LOCAL_AI_CTX", "4096")), 8192))
            gpu_layers = max(0, min(int(os.getenv("LOCAL_AI_GPU_LAYERS", "30")), 99))
            threads = max(2, min(int(os.getenv("LOCAL_AI_THREADS", "6")), 16))

            args = [str(server)]
            if self.model_path is not None:
                size = self.model_path.stat().st_size
                self.model_label = self.model_path.stem
                _progress(progress, f"Найдена готовая Qwen GGUF: {self.model_path.name} ({_human_bytes(size)}).")
                _progress(progress, "Повторно скачивать модель не нужно. Загружаю её в память…")
                args += ["-m", str(self.model_path)]
            else:
                self.model_label = hf_model
                _progress(progress, "Готовый qwen3:4b/Ollama и Qwen GGUF не найдены.")
                _progress(progress, f"Резерв: {hf_model}. При первом запуске llama.cpp скачает её один раз.")
                args += ["-hf", hf_model]

            probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                probe.settimeout(0.2)
                occupied = probe.connect_ex((self.host, self.port)) == 0
            finally:
                probe.close()
            if occupied:
                self.port = _free_port()
                _progress(progress, f"Порт 8089 занят; использую свободный порт {self.port}.")

            args += [
                "--alias", API_MODEL_ALIAS,
                "--host", self.host,
                "--port", str(self.port),
                "--cors-origins", "localhost",
                "--no-webui",
                "--reasoning", "off",
                "--reasoning-budget", "0",
                "-c", str(ctx),
                "-ngl", str(gpu_layers),
                "-t", str(threads),
                "--parallel", "1",
            ]

            log_dir = app_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            self.log_handle = open(log_dir / "llama-server.log", "w", encoding="utf-8", errors="replace")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                args,
                cwd=str(app_data_dir()),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            self.managed = True
            self._export_env()
            _progress(progress, f"llama.cpp запущен (PID {self.process.pid}). Thinking отключён. Жду загрузки модели…")

    def wait_until_ready(self, timeout: float = 600.0, progress: ProgressCallback = None) -> bool:
        started = time.monotonic()
        deadline = started + timeout
        next_status = started + 3.0
        while time.monotonic() < deadline:
            process = self.process
            if self.managed and process is not None and process.poll() is not None:
                tail = self._log_tail()
                if tail:
                    _progress(progress, f"{self.backend} завершился. Последние строки лога:\n" + tail)
                return False

            if self.backend == "ollama":
                model = _probe_ollama(timeout=1.0)
                if model:
                    self.api_model = model
                    self.model_label = model
                    self._export_env()
                    elapsed = int(time.monotonic() - started)
                    _progress(progress, f"Локальный ИИ готов за {elapsed} с. Backend: Ollama, модель: {model}. Thinking отключаем через /no_think.")
                    return True
            elif self.healthy(timeout=1.0):
                elapsed = int(time.monotonic() - started)
                self._export_env()
                _progress(progress, f"Локальный ИИ готов за {elapsed} с. Backend: {self.backend}, модель: {self.model_label}.")
                return True

            now = time.monotonic()
            if now >= next_status:
                elapsed = int(now - started)
                _progress(progress, f"Подготовка {self.model_label}… {elapsed} с.")
                tail = self._log_tail(5)
                if tail and tail != self._last_log_report:
                    self._last_log_report = tail
                    interesting = [
                        line for line in tail.splitlines()
                        if any(k in line.lower() for k in ("error", "fail", "loading", "load", "%", "vram", "model", "gpu"))
                    ]
                    if interesting:
                        _progress(progress, interesting[-1][:320])
                next_status = now + 4.0
            time.sleep(0.6)
        _progress(progress, "Превышено время ожидания запуска локального ИИ.")
        return False

    def smoke_test(self, timeout: float = 90.0) -> str:
        payload = {
            "model": self.api_model,
            "messages": [
                {"role": "system", "content": "/no_think Не показывай рассуждения. Отвечай только финальным ответом."},
                {"role": "user", "content": "Ответь только одним словом: OK"},
            ],
            "temperature": 0.0,
            "max_tokens": 24,
            "stream": False,
        }
        response = requests.post(self.endpoint, json=payload, timeout=timeout)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise RuntimeError("локальный сервер вернул ответ без choices")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        content = str((message or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("локальная модель вернула пустой ответ")
        return content

    def stop(self) -> None:
        if self.managed and self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        self.managed = False
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except Exception:
                pass
            self.log_handle = None
