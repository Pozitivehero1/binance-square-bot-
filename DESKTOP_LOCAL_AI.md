# Binance Square Bot — Desktop Local AI

This branch turns the existing production bot into a Windows desktop application while preserving the proven market engine, trade math, fact locks, quality/ranking stack, publisher and adaptive analytics.

The local model writes prose only. Python remains authoritative for market data, direction, Entry/SL/TP values, publication safety, repetition checks and ranking.

## Default profile for MSI GV72 8RD / GTX 1050 Ti / 16 GB RAM

- Model: `Qwen/Qwen3-4B-GGUF:Q5_K_M`
- Context: 4096 tokens
- GPU offload: 24 layers through the Vulkan llama.cpp build
- CPU threads: 6
- Parallel slots: 1
- Thinking mode: disabled with `/no_think`
- Candidate batches: 2 independent editorial passes

The Q5 profile is the default because it gives the local author more precision than Q4 while still fitting comfortably in system RAM. If generation is too slow or the laptop is under heavy load, the GUI has a Q4_K_M profile with more GPU offload.

## Why quality is not delegated to a 4B model

The desktop build intentionally keeps the existing quality pipeline:

1. Python builds the factual semantic package from live market data.
2. Local Qwen creates several differently worded candidates.
3. Existing fact and numeric consistency validators reject invented numbers and unsupported claims.
4. Existing language, human-feed, similarity, repetition and quality ranking selects the strongest surviving draft.
5. Python injects the canonical public Entry / Stop / TP1 / TP2 / TP3 block when a valid trade plan exists.
6. Existing publication preflight and live-price checks remain authoritative.

If the local model cannot produce a draft that survives those checks, the publishing slot is skipped instead of silently posting weaker template text. External Groq/Mistral/OpenRouter fallback is disabled by default and can be enabled in the GUI only as an emergency option.

## Desktop UI

`desktop_app.py` provides:

- Start / Stop controls
- manual `Post now`
- 20-minute default schedule
- live vs DRY_RUN publishing switch
- protected Binance credentials fields
- Quality (Q5) and Balanced (Q4) local model profiles
- local AI health check
- embedded worker logs
- persistent configuration under `%LOCALAPPDATA%\BinanceSquareBot`

The bot scan runs in a child process. A failed scan therefore does not terminate the desktop UI. The llama.cpp server is also managed separately by the application.

## Model download

The GGUF model is not embedded into every EXE update. On first local-AI start, bundled llama.cpp uses its `-hf` model reference and downloads the selected official Qwen GGUF into the normal llama.cpp/Hugging Face cache. Later starts reuse the cached model.

## Building the EXE

The GitHub Actions workflow `.github/workflows/build_windows_desktop.yml`:

1. installs the existing Python requirements and PyInstaller;
2. downloads the current official Windows Vulkan llama.cpp runtime;
3. runs the local-provider smoke test;
4. packages the complete bot, dashboard/assets and llama.cpp runtime into `BinanceSquareBot.exe`;
5. uploads the EXE as the `BinanceSquareBot-Windows` workflow artifact.

The EXE does not require a separate Python installation.

## Important local variables

```text
LOCAL_AI_ENABLED=1
LOCAL_AI_REMOTE_FALLBACK=0
LOCAL_AI_HF_MODEL=Qwen/Qwen3-4B-GGUF:Q5_K_M
LOCAL_AI_MODEL_NAME=Qwen3-4B-Q5_K_M
LOCAL_AI_CTX=4096
LOCAL_AI_GPU_LAYERS=24
LOCAL_AI_THREADS=6
LOCAL_AI_BATCHES=2
LOCAL_AI_PORT=8089
```

Use the Q4 profile in the desktop UI if Q5 generation is too slow. Do not increase context on this GPU without a concrete need: longer context consumes additional memory but does not improve these short Binance Square posts by itself.
