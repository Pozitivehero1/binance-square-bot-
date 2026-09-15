"""Windows desktop shell for Binance Square Bot with a local Qwen author."""
from __future__ import annotations

from datetime import datetime, timedelta
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict

import requests
from dotenv import dotenv_values

from local_ai_runtime import LocalAIServer, app_data_dir

APP_TITLE = "Binance Square Bot — Local AI"
MODEL_QUALITY = "Qwen3 4B Q5_K_M — качество"
MODEL_BALANCED = "Qwen3 4B Q4_K_M — быстрее"
MODEL_MAP = {
    MODEL_QUALITY: ("Qwen/Qwen3-4B-GGUF:Q5_K_M", "Qwen3-4B-Q5_K_M", "24"),
    MODEL_BALANCED: ("Qwen/Qwen3-4B-GGUF:Q4_K_M", "Qwen3-4B-Q4_K_M", "30"),
}


def config_path() -> Path:
    return app_data_dir() / "desktop.env"


def _default_config() -> Dict[str, str]:
    base = app_data_dir()
    return {
        "SQUARE_API": "",
        "BINANCE_SQUARE_OPENAPI_KEY": "",
        "DRY_RUN": "1",
        "CONTENT_MODE": "ai_author",
        "AI_AUTHOR_REQUIRED": "1",
        "LOCAL_AI_ENABLED": "1",
        "LOCAL_AI_REMOTE_FALLBACK": "0",
        "LOCAL_AI_HF_MODEL": "Qwen/Qwen3-4B-GGUF:Q5_K_M",
        "LOCAL_AI_MODEL_NAME": "Qwen3-4B-Q5_K_M",
        "LOCAL_AI_PORT": "8089",
        "LOCAL_AI_CTX": "4096",
        "LOCAL_AI_GPU_LAYERS": "24",
        "LOCAL_AI_THREADS": "6",
        "LOCAL_AI_BATCHES": "2",
        "LOCAL_AI_TIMEOUT": "110",
        "LOCAL_AI_MAX_TOKENS": "1500",
        "MIN_GLOBAL_INTERVAL_MIN": "20",
        "ENABLE_PACING_LIMITS": "0",
        "STATE_DIR": str(base / "state"),
        "LOG_FILE": str(base / "logs" / "bot.log"),
        "MPLBACKEND": "Agg",
    }


def load_config() -> Dict[str, str]:
    defaults = _default_config()
    path = config_path()
    if path.exists():
        values = dotenv_values(path)
        for key, value in values.items():
            if key and value is not None:
                defaults[str(key)] = str(value)
    return defaults


def save_config(values: Dict[str, str]) -> None:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = _default_config()
    ordered.update({k: str(v) for k, v in values.items()})
    lines = ["# Binance Square Bot desktop settings"]
    for key, value in ordered.items():
        clean = str(value).replace("\r", "").replace("\n", "")
        lines.append(f"{key}={clean}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def apply_config_to_env(values: Dict[str, str]) -> None:
    for key, value in values.items():
        os.environ[str(key)] = str(value)
    base = app_data_dir()
    os.environ["STATE_DIR"] = str(base / "state")
    os.environ["LOG_FILE"] = str(base / "logs" / "bot.log")
    os.environ["MPLBACKEND"] = "Agg"
    os.environ["LOCAL_AI_ENDPOINT"] = f"http://127.0.0.1:{values.get('LOCAL_AI_PORT', '8089')}/v1/chat/completions"


def _run_bot_worker() -> int:
    """Run one production scan/publish cycle inside a worker process."""
    cfg = load_config()
    apply_config_to_env(cfg)

    from runtime import PROJECT_DIR, load_project_env

    load_project_env()
    os.chdir(PROJECT_DIR)

    from runtime_release import activate_release
    activate_release()

    from openrouter_fallback_chain import install_openrouter_fallback_chain, verify_openrouter_fallback_chain
    from groq_primary import install_groq_primary, install_provider_source_tracking, verify_groq_primary
    from local_ai_primary import install_local_ai_primary, install_local_source_tracking, verify_local_ai_primary
    from reach_recovery_v11_8 import activate_reach_recovery
    from author_pool_policy import install_author_pool_policy, verify_author_policy
    from reach_recovery_live_exit import activate_live_recovery_exit
    from v11_9_writer_policy import install_v119_writer_policy, verify_v119_writer_policy
    from throughput_policy import install_throughput_policy, verify_throughput_policy

    install_openrouter_fallback_chain()
    install_groq_primary()
    install_local_ai_primary()
    activate_reach_recovery()
    install_author_pool_policy()
    install_v119_writer_policy()
    activate_live_recovery_exit()
    install_throughput_policy()
    install_provider_source_tracking()
    install_local_source_tracking()

    verify_openrouter_fallback_chain()
    verify_groq_primary(require_key=False)
    verify_local_ai_primary()
    verify_author_policy()
    verify_v119_writer_policy()
    verify_throughput_policy()

    import recovery_guard
    import writer

    if not getattr(recovery_guard.evaluate_recovery_candidate, "_v118_live_recovery_exit", False):
        raise RuntimeError("live recovery exit was not installed")
    if writer._build_generated.__module__ != "reach_recovery_v11_8":
        raise RuntimeError("v11.8 TRADE AI handoff was not installed")

    from main import main
    sys.argv = [sys.argv[0]]
    return int(main() or 0)


def _worker_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable, "--worker"]
    return [sys.executable, str(Path(__file__).resolve()), "--worker"]


class DesktopApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("940x700")
        self.minsize(820, 620)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.cfg = load_config()
        apply_config_to_env(self.cfg)
        self.ai_server = LocalAIServer()
        self.worker: subprocess.Popen | None = None
        self.running = False
        self.next_run: datetime | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self._style()
        self._build_ui()
        self.after(250, self._drain_log_queue)
        self.after(1000, self._tick)
        self._append_log(f"Настройки: {config_path()}")
        self._refresh_status_labels()

    def _style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("Title.TLabel", font=("Segoe UI", 18, "bold"))
        style.configure("Header.TLabel", font=("Segoe UI", 11, "bold"))
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        style.configure("TButton", padding=7)

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Binance Square Bot", style="Title.TLabel").grid(row=0, column=0, sticky="w")
        ttk.Label(root, text="локальный автор + существующие fact-lock/quality проверки").grid(row=1, column=0, sticky="w", pady=(0, 12))

        status = ttk.LabelFrame(root, text="Состояние", padding=10)
        status.grid(row=2, column=0, sticky="ew")
        status.columnconfigure(1, weight=1)
        ttk.Label(status, text="Бот:").grid(row=0, column=0, sticky="w")
        self.bot_status = ttk.Label(status, text="Остановлен", style="Status.TLabel")
        self.bot_status.grid(row=0, column=1, sticky="w", padx=(8, 24))
        ttk.Label(status, text="Локальный ИИ:").grid(row=0, column=2, sticky="w")
        self.ai_status = ttk.Label(status, text="не запущен", style="Status.TLabel")
        self.ai_status.grid(row=0, column=3, sticky="w", padx=(8, 24))
        ttk.Label(status, text="Следующий запуск:").grid(row=1, column=0, sticky="w", pady=(7, 0))
        self.next_status = ttk.Label(status, text="—")
        self.next_status.grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0), pady=(7, 0))

        settings = ttk.LabelFrame(root, text="Настройки", padding=10)
        settings.grid(row=3, column=0, sticky="ew", pady=(12, 0))
        settings.columnconfigure(1, weight=1)

        ttk.Label(settings, text="SQUARE_API:").grid(row=0, column=0, sticky="w", pady=4)
        self.square_var = tk.StringVar(value=self.cfg.get("SQUARE_API", ""))
        ttk.Entry(settings, textvariable=self.square_var, show="•").grid(row=0, column=1, sticky="ew", padx=(10, 0), pady=4)

        ttk.Label(settings, text="Binance OpenAPI key:").grid(row=1, column=0, sticky="w", pady=4)
        self.binance_var = tk.StringVar(value=self.cfg.get("BINANCE_SQUARE_OPENAPI_KEY", ""))
        ttk.Entry(settings, textvariable=self.binance_var, show="•").grid(row=1, column=1, sticky="ew", padx=(10, 0), pady=4)

        ttk.Label(settings, text="Локальная модель:").grid(row=2, column=0, sticky="w", pady=4)
        current_hf = self.cfg.get("LOCAL_AI_HF_MODEL", "")
        initial_model = MODEL_QUALITY if "Q5" in current_hf else MODEL_BALANCED
        self.model_var = tk.StringVar(value=initial_model)
        ttk.Combobox(settings, textvariable=self.model_var, values=list(MODEL_MAP), state="readonly").grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=4)

        ttk.Label(settings, text="Интервал постов, мин:").grid(row=3, column=0, sticky="w", pady=4)
        self.interval_var = tk.IntVar(value=max(5, int(self.cfg.get("MIN_GLOBAL_INTERVAL_MIN", "20"))))
        ttk.Spinbox(settings, from_=5, to=180, textvariable=self.interval_var, width=10).grid(row=3, column=1, sticky="w", padx=(10, 0), pady=4)

        self.live_var = tk.BooleanVar(value=self.cfg.get("DRY_RUN", "1") != "1")
        ttk.Checkbutton(settings, text="Реальная публикация (снять DRY_RUN)", variable=self.live_var).grid(row=4, column=1, sticky="w", padx=(10, 0), pady=4)
        self.remote_var = tk.BooleanVar(value=self.cfg.get("LOCAL_AI_REMOTE_FALLBACK", "0") == "1")
        ttk.Checkbutton(settings, text="Разрешить внешний AI только как аварийный резерв", variable=self.remote_var).grid(row=5, column=1, sticky="w", padx=(10, 0), pady=4)

        controls = ttk.Frame(root)
        controls.grid(row=4, column=0, sticky="ew", pady=12)
        self.start_btn = ttk.Button(controls, text="▶ Запустить", command=self.start_bot)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(controls, text="■ Остановить", command=self.stop_bot)
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(controls, text="Сохранить", command=self.save_settings).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Пост сейчас", command=self.run_now).pack(side="left", padx=(0, 8))
        ttk.Button(controls, text="Проверить ИИ", command=self.test_ai).pack(side="left")
        ttk.Button(controls, text="Логи", command=self.open_logs).pack(side="right")

        log_frame = ttk.LabelFrame(root, text="Лог", padding=8)
        log_frame.grid(row=5, column=0, sticky="nsew")
        root.rowconfigure(5, weight=1)
        root.columnconfigure(0, weight=1)
        self.log_text = tk.Text(log_frame, wrap="word", height=18, font=("Consolas", 9))
        scroll = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scroll.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _collect_settings(self) -> Dict[str, str]:
        values = dict(self.cfg)
        hf_model, model_name, gpu_layers = MODEL_MAP[self.model_var.get()]
        values.update({
            "SQUARE_API": self.square_var.get().strip(),
            "BINANCE_SQUARE_OPENAPI_KEY": self.binance_var.get().strip(),
            "DRY_RUN": "0" if self.live_var.get() else "1",
            "LOCAL_AI_ENABLED": "1",
            "LOCAL_AI_REMOTE_FALLBACK": "1" if self.remote_var.get() else "0",
            "LOCAL_AI_HF_MODEL": hf_model,
            "LOCAL_AI_MODEL_NAME": model_name,
            "LOCAL_AI_GPU_LAYERS": gpu_layers,
            "LOCAL_AI_BATCHES": "2",
            "MIN_GLOBAL_INTERVAL_MIN": str(max(5, int(self.interval_var.get()))),
        })
        return values

    def save_settings(self) -> None:
        self.cfg = self._collect_settings()
        save_config(self.cfg)
        apply_config_to_env(self.cfg)
        self._append_log("Настройки сохранены.")

    def _append_log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.insert("end", f"[{stamp}] {text.rstrip()}\n")
        self.log_text.see("end")

    def _queue_log(self, text: str) -> None:
        self.log_queue.put(text)

    def _drain_log_queue(self) -> None:
        try:
            while True:
                self._append_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass
        self.after(250, self._drain_log_queue)

    def _prepare_ai(self, then_run: bool) -> None:
        try:
            self._queue_log("Запускаю локальный Qwen через llama.cpp…")
            self.ai_server = LocalAIServer()
            self.ai_server.start()
            if not self.ai_server.wait_until_ready():
                raise RuntimeError("llama.cpp завершился до готовности модели; см. llama-server.log")
            self._queue_log("Локальный ИИ готов. Все тексты идут через Qwen + существующие проверки бота.")
            self.after(0, self._refresh_status_labels)
            if then_run:
                self.after(0, self._launch_worker)
        except Exception as exc:
            self._queue_log(f"Ошибка локального ИИ: {exc}")
            self.after(0, self._refresh_status_labels)
            self.running = False

    def start_bot(self) -> None:
        if self.running:
            return
        self.save_settings()
        self.running = True
        self.next_run = None
        self._refresh_status_labels()
        threading.Thread(target=self._prepare_ai, args=(True,), daemon=True).start()

    def stop_bot(self) -> None:
        self.running = False
        self.next_run = None
        if self.worker is not None and self.worker.poll() is None:
            self._append_log("Останавливаю активный цикл…")
            self.worker.terminate()
        self._refresh_status_labels()

    def run_now(self) -> None:
        self.save_settings()
        if not self.ai_server.healthy():
            threading.Thread(target=self._prepare_ai, args=(True,), daemon=True).start()
            return
        self._launch_worker()

    def _launch_worker(self) -> None:
        if self.worker is not None and self.worker.poll() is None:
            self._append_log("Цикл уже выполняется — второй одновременно не запускаю.")
            return
        apply_config_to_env(self.cfg)
        env = os.environ.copy()
        env.update({k: str(v) for k, v in self.cfg.items()})
        env["LOCAL_AI_ENDPOINT"] = self.ai_server.base_url + "/v1/chat/completions"
        flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        self.worker = subprocess.Popen(
            _worker_command(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=flags,
        )
        self.bot_status.configure(text="Выполняет цикл")
        self._append_log("Запущен новый цикл сканирования/публикации.")
        threading.Thread(target=self._read_worker_output, daemon=True).start()
        threading.Thread(target=self._wait_worker, daemon=True).start()

    def _read_worker_output(self) -> None:
        worker = self.worker
        if worker is None or worker.stdout is None:
            return
        for line in worker.stdout:
            self._queue_log(line.rstrip())

    def _wait_worker(self) -> None:
        worker = self.worker
        if worker is None:
            return
        code = worker.wait()
        self._queue_log(f"Цикл завершён, код {code}.")
        if self.running:
            minutes = max(5, int(self.cfg.get("MIN_GLOBAL_INTERVAL_MIN", "20")))
            self.next_run = datetime.now() + timedelta(minutes=minutes)
        self.after(0, self._refresh_status_labels)

    def _tick(self) -> None:
        if self.running and self.next_run is not None and datetime.now() >= self.next_run:
            self.next_run = None
            self._launch_worker()
        self._refresh_status_labels()
        self.after(1000, self._tick)

    def _refresh_status_labels(self) -> None:
        if self.worker is not None and self.worker.poll() is None:
            bot = "Выполняет цикл"
        else:
            bot = "Запущен" if self.running else "Остановлен"
        self.bot_status.configure(text=bot)
        self.ai_status.configure(text="готов" if self.ai_server.healthy(timeout=0.25) else "не запущен")
        if self.next_run is None:
            self.next_status.configure(text="после текущего цикла" if self.running else "—")
        else:
            delta = max(0, int((self.next_run - datetime.now()).total_seconds()))
            self.next_status.configure(text=f"{self.next_run:%H:%M:%S} (через {delta // 60:02d}:{delta % 60:02d})")

    def test_ai(self) -> None:
        self.save_settings()
        def work() -> None:
            try:
                if not self.ai_server.healthy():
                    self.ai_server.start()
                    if not self.ai_server.wait_until_ready():
                        raise RuntimeError("модель не запустилась")
                payload = {
                    "model": self.cfg.get("LOCAL_AI_MODEL_NAME", "Qwen3-4B-Q5_K_M"),
                    "messages": [{"role": "user", "content": "/no_think Ответь строго JSON: {\"ok\":true}"}],
                    "temperature": 0.2,
                    "max_tokens": 64,
                    "stream": False,
                }
                response = requests.post(self.ai_server.base_url + "/v1/chat/completions", json=payload, timeout=60)
                response.raise_for_status()
                self._queue_log("Тест локального ИИ пройден.")
            except Exception as exc:
                self._queue_log(f"Тест локального ИИ не пройден: {exc}")
        threading.Thread(target=work, daemon=True).start()

    def open_logs(self) -> None:
        folder = app_data_dir() / "logs"
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            os.startfile(folder)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo(APP_TITLE, str(folder))

    def _on_close(self) -> None:
        self.stop_bot()
        self.ai_server.stop()
        self.destroy()


def main() -> int:
    if "--worker" in sys.argv:
        try:
            return _run_bot_worker()
        except Exception as exc:
            print(f"DESKTOP WORKER FATAL: {type(exc).__name__}: {exc}", flush=True)
            return 1
    app = DesktopApp()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
