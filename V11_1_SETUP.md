# v11.1 setup

1. Replace repository files with this archive.
2. Keep existing GitHub Secrets:
   - `SQUARE_API`
   - `ORCAROUTER_API_KEY`
   - `MISTRAL_API`
3. **Do not delete the GitHub Actions state cache.** v11.1 safely migrates it. Existing v11 Outcome rows are automatically quarantined and will not publish follow-ups.
4. Keep the external workflow trigger cadence unchanged.
5. Dashboard auto-refresh remains enabled: `17 * * * *`.
6. No new secrets are required. The supplied PozitiveHero avatar is already bundled.

Expected log markers after a plan-valid publication:

```text
PUBLIC TEXT CONTRACT PASS ACEUSDT: direction + entry + SL + TP1/TP2/TP3 are explicit
Outcome journal: tracking setup=setup_... source_post_id=... ACEUSDT LONG | full public plan TP1/TP2/TP3
```

On the first run after upgrading from v11 you may also see:

```text
Outcome journal migration: quarantined N pre-v11.1 setup(s)
```

This is intentional. Old reconstructed setups are not trusted.

DeepSeek transient failures look like:

```text
DeepSeek attempt 1/4 failed: HTTP 429 ... retrying in ...
AI author provider=deepseek_v4_pro ... attempt=2/4
```

If all DeepSeek attempts fail, Mistral is used as fallback.
