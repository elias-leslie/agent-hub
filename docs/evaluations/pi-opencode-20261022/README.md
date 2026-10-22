# Pi and OpenCode free-model verification — 2026-10-22

Task: `task-f8c962cd93df4abf`. The requested free models are discoverable in Pi 1.4.0, but neither produced a response through the tested paths. Do not route Neri workflows to them on this evidence. No Neri target data, paid fallback, client-identity spoofing, deployment, or publication was performed in this evaluation.

## Service and configuration

The current service is OpenCode Console inference, previously documented as Zen. The exact provider/model selections are:

- `opencode/deepseek-v4.1-flash-free`
- `opencode/glm-5.3-flash-free`

Both are built into Pi 1.4.0; no provider extension or custom model definition is needed. Pi documents `/login` and its private `~/.pi/agent/auth.json` store, with an `api_key` credential under `opencode`; `OPENCODE_API_KEY` is the environment alternative. Local `pi auth check` confirmed credential resolution, which is distinct from remote authorization.

OpenCode's [model documentation](https://opencode.ai/v2/docs/console/models/) lists both free variants at $0 for input, output, and cached reads, for a limited time. It gives no end date or numeric free-model request/token quota. Paid names without `-free` are different selections: DeepSeek is $0.30 input / $1.20 output / $0.006 cached read per million tokens; GLM is $0.15 / $0.50 / $0.03. No paid selection was tested.

The [inference documentation](https://opencode.ai/v2/docs/console/api/inference/) describes bearer API keys and the OpenAI-compatible `/inference/openai/v1/chat/completions` endpoint. Pi's bundled provider uses `/inference/v1`. No endpoint or identity override was applied. The [key documentation](https://opencode.ai/v2/docs/console/api/) defines Models → Request as the narrow inference permission.

Pi references: [version 1.4.0 provider documentation](https://github.com/earendil-works/pi/blob/v1.4.0/packages/coding-agent/docs/providers.md), [model documentation](https://github.com/earendil-works/pi/blob/v1.4.0/packages/coding-agent/docs/models.md). The installed, unmodified package was checked directly as well.

## Observed calls

Each call used one tiny synthetic filtering/arithmetic JSON task. Pi had tools, extensions, MCP, skills, templates, and context files disabled for these two model calls. Neither returned assistant text. [results.json](results.json) retains content-free model, native-session, error, latency, and usage evidence.

| Harness | Model | Wall time | Provider duration | Result |
| --- | --- | ---: | ---: | --- |
| Pi 1.4.0 | DeepSeek V4.1 Flash Free | 0.337 s | 137 ms | HTTP 403 `FreeTierError` |
| Pi 1.4.0 | GLM-5.3-Flash Free | 0.404 s | 199 ms | HTTP 403 `FreeTierError` |
| OpenCode 2.1.3 standalone, anonymous | DeepSeek V4.1 Flash Free | 0.740 s | Not reported | Same HTTP 403 free-tier restriction |
| OpenCode 2.1.3 standalone, authorized service key | GLM-5.3-Flash Free | 0.708 s | Not reported | HTTP 403; Console reconnection requested |

The Pi response explicitly restricts the free tier to use inside OpenCode. Pi exited 0 despite `stopReason: error`; a successful process exit is not model success. These are rejection latencies, not inference-speed measurements. Both Pi responses report zero input/output/cache tokens and zero native cost. OpenCode's native errors reported no usage. After the attempts the signed-in service-account Console still showed $0.00, zero recorded requests, and zero tokens. This is the observed display, not an independent invoice reconciliation or a guarantee about future pricing.

The official CLI was installed through managed admission into disposable storage and tested with separate XDG data/config/cache/state directories, a standalone server, and tool-denial policies. No native Console-account login was completed. The service-key path returned a reconnection error, so native account login remains unverified. The interactive supported command for that separate path is `opencode auth login opencode --standalone`; do not infer that reconnecting will make either model available in Pi. [CLI documentation](https://opencode.ai/v2/docs/cli/commands/).

There is no response-quality evidence for extraction, summaries, classification, coding, or any Neri workflow. Neither model is qualified for a workflow yet. Numeric rate limits were not measured; authorization failed first.

## Credential handling and cleanup

The logged-in Console account was used. Its pre-existing key was expired. New keys used Restricted permissions, Models → Request only, all other resources None, and a 30-day expiration. The first unused key appeared in tool output because the initial redaction did not recognize the new prefix; it was revoked and the revoked state verified before any inference attempt. A replacement was transferred directly in memory to Pi's supported store, mode 0600, without being emitted.

After the failed tests, the replacement was also revoked and its revoked state verified in Console. Only the `opencode` entry was removed from Pi's auth store; the existing Anthropic, MiniMax, and OpenAI entries were preserved. `pi auth check --provider opencode --json --no-refresh` now reports `credentials_not_configured`, and the file remains 0600. No active test grant remains. Existing account logins were preserved.

Scratch CLI/config/raw synthetic output is under `/srv/scratch/pi-opencode-synthetic-20261022`; it contains no retained API key. Native Pi transcripts remain in Pi's normal session store for ingestion verification. Scratch data is disposable after final verification; this report and content-free results are the durable evidence.

## Agent Hub ingestion defect and fix

The supported Pi adapter installer check passed. Syncing the native synthetic transcripts failed with PostgreSQL SQLSTATE `22P02`: `pi_sync.py` writes `session_type=pi`, but both the ORM enum and the production database enum lacked that member. The initial live database was at migration `d4f2a6c8e0b1`. Queries inspected session identity/types and enum metadata only; prompt text was not copied into this report.

The fix adds `pi` to `Session.session_type` and migration `e3a7c9d1f502`, which appends the value idempotently. Downgrade leaves the additive value intact so persisted history stays readable. No other harness type is added.

Validation in the isolated checkout:

- A managed integration test reproduced the exact PostgreSQL invalid-enum error before the fix.
- `st check pytest -- tests/integration/test_pi_session_type.py --run-integration`: 2 passed. It checks real migrated PostgreSQL writes and ORM reads, plus migration idempotency/preservation against a transaction-local temporary enum.
- `st check pytest -- tests/services/session_ingestion/test_pi.py`: 7 passed.
- `st check ruff -- backend/app/models/session.py backend/alembic/versions/e3a7c9d1f502_add_pi_session_type.py backend/tests/integration/test_pi_session_type.py`: passed.
- Independent native review requested as `gpt-6.1-sol` at `xhigh`: accepted by the client, no blocking findings. The reviewer inspected the three scoped code/test files and the raw red/green test logs without edits or deployment. Separate delivered-model telemetry was unavailable.

Post-deployment ingestion evidence is recorded with the final checkpoint. Unit/integration passes do not establish that production has received the migration. Live attribution remains unverified until the coordinator lands/deploys and reruns native transcript sync.
