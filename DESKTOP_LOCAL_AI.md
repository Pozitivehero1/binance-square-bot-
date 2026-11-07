# Binance Square Bot — Desktop Local AI

This branch turns the existing production bot into a Windows desktop application while preserving the market engine, trade math, fact locks, quality/ranking stack, publisher and adaptive analytics.

The local model writes prose only. Python remains authoritative for market data, direction, Entry/SL/TP values, publication safety, repetition checks and ranking.

## Default profile for MSI GV72 8RD / GTX 1050 Ti / 16 GB RAM

The desktop app now offers three profiles:

- **Maximum quality (default):** `Qwen/Qwen3-8B-GGUF:Q4_K_M`, 4096-token context, 18 GPU-offloaded layers, 6 CPU threads.
- **Optimal:** `Qwen/Qwen3-4B-GGUF:Q5_K_M`, 4096-token context, 24 GPU-offloaded layers.
- **Faster:** `Qwen/Qwen3-4B-GGUF:Q4_K_M`, 4096-token context, 30 GPU-offloaded layers.

All profiles use one llama.cpp inference slot and two independent editorial candidate batches. Qwen thinking mode is disabled with `/no_think`; the bot spends the saved compute on candidate diversity and deterministic validation instead.

The 8B Q4 profile is intentionally the default for this laptop. Its weights are larger than the GTX 1050 Ti VRAM, so llama.cpp uses partial GPU offload and system RAM rather than trying to fit the whole model on the GPU.

## Quality policy

A local 8B model cannot honestly be guaranteed to beat every raw answer from a much larger remote model. The desktop build therefore does not make model size the quality gate. It keeps the existing production pipeline and makes the model responsible only for wording:

1. Python builds the factual semantic package from live market data.
2. Local Qwen creates multiple differently worded candidates.
3. Existing fact and numeric consistency validators reject invented numbers and unsupported claims.
4. Existing language, human-feed, similarity, repetition and quality ranking selects the strongest surviving draft.
5. Python injects the canonical public Entry / Stop / TP1 / TP2 / TP3 block when a valid trade plan exists.
6. Existing publication preflight and live-price checks remain authoritative.
7. If no local candidate meets the existing contract, the slot is skipped instead of publishing deliberately weaker copy.

This is the practical quality floor: local AI cannot bypass the checks that protected the remote-AI version. External Groq/Mistral/OpenRouter fallback is disabled by default and can be enabled in the GUI only as an emergency option.

## Desktop UI

`desktop_app.py` provides:

- Start / Stop controls
- manual `Post now`
- 20-minute default schedule
- live vs DRY_RUN publishing switch
- protected Binance credentials fields
- Maximum quality (8B), Optimal (4B Q5), and Faster (4B Q4) local profiles
- local AI health check
- embedded worker logs
- persistent configuration under `%LOCALAPPDATA%\BinanceSquareBot`

The bot scan runs in a child process. A failed scan therefore does not terminate the desktop UI. The llama.cpp server is managed separately by the application.

## Model download

The GGUF model is not embedded into every EXE update. On first local-AI start, bundled llama.cpp uses its `-hf` model reference and downloads the selected official Qwen GGUF into the normal llama.cpp/Hugging Face cache. Later starts reuse the cached model.

The default 8B Q4 model is roughly a 5 GB download. Internet is still required for Binance market data and publishing; only text generation runs locally after the model is cached.

## Building the EXE

The GitHub Actions workflow `.github/workflows/build_windows_desktop.yml`:

1. installs the existing Python requirements and PyInstaller;
2. finds a current official Windows x64 Vulkan llama.cpp nightly runtime;
3. runs the local-provider smoke test;
4. packages the complete bot, dashboard/assets and llama.cpp runtime into `BinanceSquareBot.exe`;
5. uploads the EXE as the `BinanceSquareBot-Windows` workflow artifact.

The EXE does not require a separate Python installation.

## Important local variables

```text
LOCAL_AI_ENABLED=1
LOCAL_AI_REMOTE_FALLBACK=0
LOCAL_AI_HF_MODEL=Qwen/Qwen3-8B-GGUF:Q4_K_M
LOCAL_AI_MODEL_NAME=Qwen3-8B-Q4_K_M
LOCAL_AI_CTX=4096
LOCAL_AI_GPU_LAYERS=18
LOCAL_AI_THREADS=6
LOCAL_AI_BATCHES=2
LOCAL_AI_PORT=8089
```

If the 8B profile is too slow on this specific laptop, switch to the 4B Q5 profile before reducing the existing publication-quality thresholds. Do not increase context unless a concrete prompt needs it: longer context consumes additional RAM/VRAM but does not by itself improve these short Binance Square posts.
