"""Start/stop the bundled llama.cpp server used by the desktop application."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from typing import Optional

import requests


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


class LocalAIServer:
    def __init__(self) -> None:
        self.process: Optional[subprocess.Popen] = None
        self.host = "127.0.0.1"
        self.port = int(os.getenv("LOCAL_AI_PORT", "8089"))
        self.log_handle = None

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def healthy(self, timeout: float = 1.5) -> bool:
        for path in ("/health", "/v1/models"):
            try:
                response = requests.get(self.base_url + path, timeout=timeout)
                if 200 <= response.status_code < 300:
                    return True
            except requests.RequestException:
                pass
        return False

    def start(self) -> None:
        if self.healthy():
            os.environ["LOCAL_AI_ENDPOINT"] = self.base_url + "/v1/chat/completions"
            return
        server = find_llama_server()
        if server is None:
            raise FileNotFoundError(
                "llama-server не найден. Desktop-сборка должна содержать bundled llama.cpp; "
                "для запуска из исходников установите llama.cpp через winget."
            )

        model = os.getenv("LOCAL_AI_HF_MODEL", "Qwen/Qwen3-8B-GGUF:Q4_K_M").strip()
        api_alias = os.getenv("LOCAL_AI_MODEL_NAME", "Qwen3-8B-Q4_K_M").strip() or "Qwen3-8B-Q4_K_M"
        ctx = max(2048, min(int(os.getenv("LOCAL_AI_CTX", "4096")), 8192))
        gpu_layers = max(0, min(int(os.getenv("LOCAL_AI_GPU_LAYERS", "18")), 99))
        threads = max(2, min(int(os.getenv("LOCAL_AI_THREADS", "6")), 16))
        args = [
            str(server),
            "-hf", model,
            "--alias", api_alias,
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
        self.log_handle = open(log_dir / "llama-server.log", "a", encoding="utf-8", errors="replace")
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.process = subprocess.Popen(
            args,
            cwd=str(app_data_dir()),
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        os.environ["LOCAL_AI_ENDPOINT"] = self.base_url + "/v1/chat/completions"

    def wait_until_ready(self, timeout: float = 1800.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                return False
            if self.healthy(timeout=2.0):
                return True
            time.sleep(1.0)
        return False

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
