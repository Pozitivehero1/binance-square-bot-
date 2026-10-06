# Runtime architecture — v11.15

## Source of truth

- Product/release version: `VERSION.txt` and the final `BOT_VERSION` set by `runtime_release.activate_release()`.
- Production entry point: `run_bot.py`.
- Orchestrator: `main.py`.
- Production workflow configuration: `.github/workflows/run.yml`.
- Safe local defaults: `env.example`.

Older module docstrings and `CHANGES_V*.md` files are historical context, not the active release identifier.

## Startup order

The order in `run_bot.py` is behaviorally significant:

1. Load project `.env` and switch to the repository directory.
2. `runtime_release.activate_release()` establishes cumulative v11.15 environment defaults.
3. Install OpenRouter fallback.
4. Install Groq primary routing.
5. Activate reach-recovery compatibility policy.
6. Install author-pool policy.
7. Install v11.9 writer policy.
8. Activate live recovery exit.
9. Install provider-source tracking.
10. Run invariant verifiers.
11. Import `main.main` and execute it.

Several steps monkey-patch imported functions. Do not reorder, remove, or rename these modules as cleanup unless regression tests prove behavior is unchanged.

## Configuration precedence

Production behavior currently has three configuration layers:

1. Module defaults.
2. Project/GitHub Actions environment.
3. Runtime overrides installed by `runtime_release` / compatibility policies.

The effective runtime value is authoritative. When diagnosing production, do not assume a value in `env.example` or a module-level default is the live value.

## Core data flow

`run_bot.py` → `main.py` → market data/indicators → candidate scoring → public trade-plan construction → AI author routing → fact/quality/publication guards → media rendering → `publisher.py` → performance/outcome stores.

## Cleanup rule

v11.15 cleanup is intentionally behavior-preserving. Historical change logs and compatibility modules stay in place until a dedicated v12 refactor can replace monkey-patching with explicit composition and prove parity through the offline suite.

## Before changing runtime policy

Run:

```bash
python config_check.py
python run_tests.py
RUN_STRESS_TESTS=1 python run_tests.py
```

At minimum, changes touching startup/provider/recovery code must keep the runtime-policy, provider, publication, recovery and self tests passing.
