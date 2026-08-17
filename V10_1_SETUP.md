# v10.1 upgrade — 3 steps

1. Replace the current repository files with the contents of the v10.1 archive. Keep the same repo/branch so the existing `square-state-*` cache can restore the accumulated analytics history.

2. In **GitHub → Settings → Secrets and variables → Actions**, add:

```text
ORCAROUTER_API_KEY = <your OrcaRouter key>
```

Keep the existing:

```text
SQUARE_API
MISTRAL_API
```

3. Run **Binance Square Bot** manually once and inspect the log. A healthy run should show either:

```text
AI author provider=deepseek_v4_pro model=deepseek/deepseek-v4-pro-free
```

or, only if the primary API fails:

```text
DeepSeek primary unavailable/unusable ... trying Mistral fallback
AI author provider=mistral fallback=true ...
```

You should also see candidate log fields like:

```text
adaptive=+...
w2e_proxy=+...
```

The dashboard should show `Adaptive ON` after the next dashboard build.

No new Binance authentication is required for public performance analytics.
