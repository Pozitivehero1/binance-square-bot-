# DeepSeek API from GitHub Actions

Configured for `Pozitivehero1/binance-square-bot-` on 13 October 2026.

## Endpoint and repository settings

OpenAI-compatible HTTPS Base URL:

```text
https://freedeepseek-api.tailfaa4e3.ts.net/v1
```

These repository variables already exist:

| Variable | Value |
| --- | --- |
| DEEPSEEK_BASE_URL | https://freedeepseek-api.tailfaa4e3.ts.net/v1 |
| DEEPSEEK_MODEL | deepseek-chat |
| DEEPSEEK_REASONING_MODEL | deepseek-reasoner |

The repository Actions secret `DEEPSEEK_API_KEY` is already stored. Its value
is the local proxy key, not a DeepSeek browser credential. No real credentials
are committed to this repository. Never print request headers or the secret.

## Verified Actions run

[Successful external Ubuntu runner test](https://github.com/Pozitivehero1/binance-square-bot-/actions/runs/38437185033)
verified health, readiness, models, capabilities, HTTP 401 without a key and
with an invalid key, chat/reasoner `OK` responses and strict Russian JSON with
three variants. The auth-file route returned 404 even with a valid API key.

[Run the manual connectivity check](https://github.com/Pozitivehero1/binance-square-bot-/actions/workflows/deepseek-api-smoke.yml):
choose **Run workflow**. Optional reasoner and JSON checks each add one model
request. There is no schedule, no automatic retry and no Binance publication.

## Use in another job in this repository

Add these environment bindings to the job or step that calls your AI client:

```yaml
env:
  DEEPSEEK_BASE_URL: ${{ vars.DEEPSEEK_BASE_URL }}
  DEEPSEEK_MODEL: ${{ vars.DEEPSEEK_MODEL }}
  DEEPSEEK_REASONING_MODEL: ${{ vars.DEEPSEEK_REASONING_MODEL }}
  DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
```

For an OpenAI SDK client, pass DEEPSEEK_BASE_URL as `base_url` and
DEEPSEEK_API_KEY as `api_key`. For HTTP, send:

```text
POST <DEEPSEEK_BASE_URL>/chat/completions
Authorization: Bearer <DEEPSEEK_API_KEY>
Content-Type: application/json

{"model":"deepseek-chat","messages":[{"role":"user","content":"Ответь ровно OK"}],"stream":false}
```

`deepseek-v4-pro` is a deprecated compatibility alias for V4.1-Flash with
thinking in this proxy. Use `deepseek-reasoner` for reasoning.

The publishing workflow passes these bindings and the production author
adapter tries DeepSeek first. Gemini/Groq/Mistral/Orca/OpenRouter retain their
existing fallback order. A failed, limited or unusable DeepSeek response
activates a cooldown and hands off without immediate retries. Fact and trade
plan validation remain unchanged. Both TRADE and EVENT attribution record
`deepseek_local` when this proxy actually wrote the prose.

`DEEPSEEK_MODEL_TIMEOUT=25` bounds the DeepSeek request; connection timeout is
at most five seconds. The existing global scan/request budget still applies.
Clear the production DEEPSEEK_API_KEY binding to revert to the original chain.
The separate **DeepSeek bot adapter check** workflow exercises the production
startup/adapter on synthetic facts without running the publisher.

## Windows operation

API installation: `C:\AI\FreeDeepseekAPI`.

- FreeDeepseekAPI Task Scheduler task starts the API at boot after 30 seconds.
- Tailscale Windows service starts automatically and runs unattended.
- `tailscale funnel --bg` persists its HTTPS proxy configuration across reboots.
- Service/process recovery is configured; no console window needs to remain open.
- Health checks run every 15 minutes without model requests.

PowerShell from the installation directory, as administrator:

```powershell
.\service-control.ps1 status all
.\service-control.ps1 restart api
.\service-control.ps1 stop funnel
.\service-control.ps1 start funnel
.\check-api.ps1 -SkipModel
```

`all` now refers to the API plus Tailscale Funnel. The unused Cloudflare task
remains disabled. To revoke public HTTPS access, stop `funnel`; the Tailscale
service can remain running. Stop the API separately if needed.

For DeepSeek reauthentication:

```powershell
.\ops\reauth.ps1
```

The Windows PC must be powered on, awake and online. Browser-session expiry
requires a new DeepSeek login. Tailscale device authentication may also need
renewal; permanent key-expiry protections were not disabled. Keep the same
device/tailnet hostname so repository DEEPSEEK_BASE_URL remains correct.

Tailscale Funnel is a beta service with bandwidth limits. Its free Personal
plan is intended for personal, non-commercial use; verify plan suitability
before commercial deployment. No paid plan or domain purchase was performed.

References: [Funnel persistence](https://tailscale.com/docs/reference/tailscale-cli/funnel),
[Tailscale plans](https://tailscale.com/pricing),
[GitHub Actions Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets).

