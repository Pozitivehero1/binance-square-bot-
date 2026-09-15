"""Robust local llama.cpp runtime used by the Windows desktop application."""
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
    explicit = (os.getenv("LLAMA_SERVER_PATH") or "").strip()
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


def _score_model(path: Path) -> int:
    name = path.name.lower()
    score = 0
    if "qwen" in name:
        score += 1000
    if "qwen3.5" in name or "qwen3_5" in name or "qwen3-5" in name:
        score += 600
    elif "qwen3" in name:
        score += 400
    for token, points in (("9b", 350), ("8b", 300), ("7b", 240), ("4b", 100)):
        if token in name:
            score += points
            break
    if "q5_k_m" in name:
        score += 140
    elif "q4_k_m" in name:
        score += 120
    elif "q4" in name:
        score += 80
    try:
        size = path.stat().st_size
        if 4 * 1024**3 <= size <= 8 * 1024**3:
            score += 120
        elif size > 2 * 1024**3:
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
        _progress(progress, f"Ищу готовую GGUF-модель в {root}…")
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
    return candidates[0]


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
        self.model_label = (os.getenv("LOCAL_AI_MODEL_NAME") or "Qwen local").strip()
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
            response = requests.get(self.base_url + "/health", timeout=timeout)
            return 200 <= response.status_code < 300
        except requests.RequestException:
            return False

    def _export_env(self) -> None:
        os.environ["LOCAL_AI_ENDPOINT"] = self.endpoint
        os.environ["LOCAL_AI_API_MODEL"] = API_MODEL_ALIAS
        if self.model_path is not None:
            os.environ["LOCAL_AI_MODEL_NAME"] = self.model_path.stem

    def _log_tail(self, limit: int = 12) -> str:
        path = app_data_dir() / "logs" / "llama-server.log"
        if not path.is_file():
            return ""
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return "\n".join(lines[-limit:])
        except OSError:
            return ""

    def start(self, progress: ProgressCallback = None) -> None:
        with self._start_lock:
            if self.healthy():
                self._export_env()
                _progress(progress, "Локальный ИИ уже запущен.")
                return
            if self.process is not None and self.process.poll() is None:
                _progress(progress, "Сервер уже запускается — жду готовности модели.")
                return

            server = find_llama_server()
            if server is None:
                raise FileNotFoundError("В сборке не найден llama-server.exe")

            self.model_path = find_installed_gguf(progress)
            hf_model = (os.getenv("LOCAL_AI_HF_MODEL") or "Qwen/Qwen3-8B-GGUF:Q4_K_M").strip()
            ctx = max(2048, min(int(os.getenv("LOCAL_AI_CTX", "4096")), 8192))
            gpu_layers = max(0, min(int(os.getenv("LOCAL_AI_GPU_LAYERS", "16")), 99))
            threads = max(2, min(int(os.getenv("LOCAL_AI_THREADS", "6")), 16))

            args = [str(server)]
            if self.model_path is not None:
                size = self.model_path.stat().st_size
                self.model_label = self.model_path.stem
                _progress(progress, f"Найдена готовая модель LM Studio: {self.model_path.name} ({_human_bytes(size)}).")
                _progress(progress, "Повторно скачивать модель не нужно. Загружаю её в память…")
                args += ["-m", str(self.model_path)]
            else:
                self.model_label = hf_model
                _progress(progress, "Готовая GGUF в стандартной папке LM Studio не найдена.")
                _progress(progress, f"Будет использована резервная модель {hf_model}; при первом запуске её загрузит llama.cpp.")
                args += ["-hf", hf_model]

            # If 8089 is occupied by something other than our healthy server, do not hang on bind.
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
                "-c", str(ctx),
                "-ngl", str(gpu_layers),
                "-t", str(threads),
                "--parallel", "1",
            ]

            log_dir = app_data_dir() / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_path = log_dir / "llama-server.log"
            self.log_handle = open(log_path, "w", encoding="utf-8", errors="replace")
            flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
            self.process = subprocess.Popen(
                args,
                cwd=str(app_data_dir()),
                stdout=self.log_handle,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            self._export_env()
            _progress(progress, f"llama.cpp запущен (PID {self.process.pid}). Жду загрузки модели…")

    def wait_until_ready(self, timeout: float = 600.0, progress: ProgressCallback = None) -> bool:
        started = time.monotonic()
        deadline = started + timeout
        next_status = started + 5.0
        while time.monotonic() < deadline:
            process = self.process
            if process is not None and process.poll() is not None:
                tail = self._log_tail()
                if tail:
                    _progress(progress, "llama.cpp завершился. Последние строки лога:\n" + tail)
                return False
            if self.healthy(timeout=1.0):
                elapsed = int(time.monotonic() - started)
                self._export_env()
                _progress(progress, f"Локальный ИИ готов за {elapsed} с. Модель: {self.model_label}.")
                return True
            now = time.monotonic()
            if now >= next_status:
                elapsed = int(now - started)
                _progress(progress, f"Загрузка модели в память… {elapsed} с.")
                tail = self._log_tail(4)
                if tail and tail != self._last_log_report:
                    self._last_log_report = tail
                    interesting = [line for line in tail.splitlines() if any(k in line.lower() for k in ("error", "fail", "loading", "load", "%", "vram", "model"))]
                    if interesting:
                        _progress(progress, interesting[-1][:300])
                next_status = now + 5.0
            time.sleep(0.75)
        _progress(progress, "Превышено время ожидания запуска локального ИИ.")
        return False

    def smoke_test(self, timeout: float = 90.0) -> str:
        payload = {
            "model": API_MODEL_ALIAS,
            "messages": [{"role": "user", "content": "/no_think Ответь только одним словом: OK"}],
            "temperature": 0.0,
            "max_tokens": 16,
            "stream": False,
        }
        response = requests.post(self.endpoint, json=payload, timeout=timeout)
        if not response.ok:
            raise RuntimeError(f"HTTP {response.status_code}: {response.text[:500]}")
        data = response.json()
        choices = data.get("choices") if isinstance(data, dict) else None
        if not choices:
            raise RuntimeError("llama.cpp вернул ответ без choices")
        content = str((choices[0].get("message") or {}).get("content") or "").strip()
        if not content:
            raise RuntimeError("локальная модель вернула пустой ответ")
        return content

    def stop(self) -> None:
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None
        if self.log_handle is not None:
            try:
                self.log_handle.close()
            except Exception:
                pass
            self.log_handle = None
