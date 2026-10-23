# Oh My Pi evaluation and Pi/OpenCode wiring cleanup — 2026-10-23

**Verdict: keep Pi; do not adopt Oh My Pi (OMP).** OMP worked, but on a matched task it used about 2.3× the tokens of Pi and took 1.6× as long. Its strengths duplicate orchestration we already have (Agent Hub, ST, Workflow), and adopting it means tracking a fork that changes daily. We took the one idea worth having, **OpenCode Go quota visibility**, into Agent Hub. The OpenCode CLI integration is removed, because we use OpenCode Go only through Pi.

## Verified facts

**Versions**
- Pi 1.4.0 (`@earendil-works/pi-coding-agent`; upstream is now `earendil-works/pi`, not `badlogic/pi-mono`).
- OMP v18.12.6 release binary, checked against the release's SHA256SUMS. Upstream `can1357/oh-my-pi` main is `0b5c27ab24`.

**OMP**
- A hard fork of pi-mono, last synced 2026-03-22 (`docs/porting-from-pi-mono.md`). It runs on Bun with about 80k lines of Rust natives and a vendored bash.
- It released daily from v18.12.2 to v18.12.6 (Oct 18–21), and had 4,166 open issues on 2026-10-23.
- Native features: `task` subagents with isolation, `orchestrate`/`workflowz`, LSP and DAP, hashline edits, MCP, a browser, model roles, and RPC/SDK/ACP entry points. Its RPC `get_state` worked headless in 0.51 s.
- Coexistence hazards:
  - It honours Pi's own `PI_CONFIG_DIR` and `PI_CODING_AGENT_DIR`.
  - It reads `~/.env`.
  - On first run it imports `.claude`, `.codex`, `.cursor` and other rules, skills and MCP servers.
  - It ships its own UI called "Agent Hub", which collides with our name.
- The test therefore ran with isolated `HOME`, `PI_CONFIG_DIR` and XDG dirs. `~/.pi` hashes and the auth key list were identical before and after.

**OpenCode Go in Pi**: already built in and working.
- Pi 1.4.0 bundles 29 `opencode-go` models (`pi-ai/dist/providers/data/opencode-go.json`, base `https://opencode.ai/inference/go[/v1]`).
- The key lives in Pi's store (`auth.json` entry `opencode-go`); `OPENCODE_API_KEY` is the env alternative.
- Select a model with `--model opencode-go/<id>`, e.g. `opencode-go/deepseek-v4.1-flash`, or through `st aico create --tool pi --model opencode-go/<id>`.
- 12 native Pi sessions had already used it, mostly deepseek-v4.1-flash.

**OpenCode Go in OMP**: first-class.
- The same API key and `OPENCODE_API_KEY` (`packages/catalog/src/compat/rules/{providers,auth}/opencode-go.kdl`), plus live model discovery and per-model compat patches.
- A quota poller (`packages/ai/src/usage/opencode-go.ts`).
- Both tools can coexist only with isolated config dirs, because of the shared `PI_*` variables.

**OpenCode Go plan** ([docs](https://opencode.ai/docs/go/)): Go is $10/month and Go Plus $40/month. Per-model limits apply across three windows, with 5 hours = 20% and a week = 50% of the monthly limit. The opt-in **"Extra usage"** setting falls back to the pay-as-you-go balance instead of blocking. The docs ask clients to send their own `User-Agent` and a stable `x-opencode-session`.

**Quota endpoint**
- `GET https://opencode.ai/zen/go/v1/usage` is **not in OpenCode's docs**; it was found in OMP's source.
- It returns `{"usage": {"rolling"|"weekly"|"monthly": {status, percent, resetsAt}}}`.
- It answers 403 without the `User-Agent` and `x-opencode-session` headers.

## Matched smoke check (one run each, [results.json](results.json))

- **Setup:** the same fixture (sum and count over 40 integers, written to `result.json`), the same model `opencode-go/deepseek-v4.1-flash`, thinking `low`, and tools `read,bash,write`.
- **Turned off in both:** extensions, skills, rules and context files.
- **Scoring:** objective, by exact JSON match.

| | Pi 1.4.0 | OMP 18.12.6 |
|---|---:|---:|
| Correct | yes | yes |
| Wall time | 6.67 s | 10.41 s |
| Model calls / tool calls | 3 / 2 | 4 / 3 |
| First-call input (incl. cache) | 1,329 | 3,658 |
| Input / cache-read / output tokens | 1,779 / 2,688 / 190 | 4,332 / 11,136 / 343 |
| Native-reported cost | $0.000389 | $0.000889 |

This is a single, non-randomised run on a tiny task, so it is descriptive only. The predeclared stop applied: there was no correctness or cost advantage for OMP, so no more runs. The quota percentages, which are integers, did not move. Not tested: subagents, LSP, long context, recovery, and vulnerability work. Those would not change the verdict, because they either duplicate Agent Hub and ST or need OMP as the daily harness.

## Why not adopt or migrate
- Our measured cost driver is coordinator overhead and model time, not harness tool speed (`../harness-efficiency-20261022`). Tool time was under 1 s per run against 30–50 s of model time.
- Each adapter we maintain for Pi would need an OMP twin, tracking a fork that diverged 7 months ago and releases daily: context extension, ingestion, Tether launch, coordination extension.
- Neri is a records system with no embedded agent, so it has no orchestration layer for OMP to slot into.

## Wiring audit and changes

Read-only audits covered Pi, OpenCode and `st aico` coordination. The owner then decided to drop the OpenCode CLI.

**OpenCode CLI removed**
- Agent Hub `ecd8656c8` (and note `a3f20d979`) removed the launcher, plugin, `sync-opencode`/`retire-opencode` and the ingestion adapter.
- Host: stopped `opencode serve --service`; removed `~/.opencode`, its config, data, cache and state, the two symlinks, and the `~/.bashrc` PATH lines (backup `~/.bashrc.bak-opencode-20261023`).
- Native history archive: `/srv/workspaces/agent-reviews/opencode-removal-20261023/`. It holds 16 sessions; credential tables were emptied and vacuumed, and a scan found no tokens.
- Not archived: credentials and the third-party provider override.
- Kept: historical Agent Hub rows, the `opencode` harness label, and the `opencode`/`opencode-go` HTTP provider ids.
- Before removal, the audits found that OpenCode roots dropped their initial prompt (`opencode mini` has no positional prompt), ran tools in a background service without Aico/ST env, had no ST handshake/lease support, and never ingested sessions started without an explicit model. These are moot now.
- Orphan `ses_e9a371c3…` closed.

**Pi fixes in Agent Hub**: `003b8dd37`, `1e380a80b`, `e672817d5`, plus fixture `84a2004a8`.
- Failed requests are now visible as `provider_metadata.request_errors` (count, category, redacted message) and a "N failed" badge in the session list, detail and efficiency views. 23 historical error events across 8 sessions are now shown. Categories: OpenAI cyber-flag, Go timeouts, Go "requires Global regions", FreeTierError and usage limits.
- Bare model labels are qualified to `provider/model`.
- Three missed transcripts (`01a16452`, `01a1647f`, `01a16538`) were backfilled. A full replay was idempotent: the second pass appended 0 events.
- Stale July Pi logs were removed.

**Handed to the Aico/Tether/A-Term merge** (owned by that agent, not edited here):
- drop the `opencode` tool
- the Pi process name is `pi`, not `pi-coding-agent`, and add Pi to `observeAgent`
- remove the duplicate `--approve`
- install and drift-check `st-coord.ts`
- optional: Pi advisory root state and the hardcoded Daybreak model

**Live verification** (Aico window "Pi Go check", `opencode-go/deepseek-v4.1-flash`):
- the initial prompt was delivered and context was delivered (`aico-widget-783e46f7`)
- the Agent Hub row `01a16927…` has provider `opencode-go` and 4 usage and 4 tool events
- an ST handshake was sent and acked
- the root ended and retired cleanly (`completed`, `tether_retired=true`)

**OpenCode Go quota in Agent Hub**: `21b336cc4` and `0a47f0297`, deployed in job `6c85a177fc3c4efe8749ba69f51c8efc`.
- The Costs page has an "OpenCode Go limits used" card below Plans and credits, showing 5 hours, Week and Month with percent, status and reset time. A line says the endpoint is unofficial.
- Route: `GET /analytics/subscriptions/opencode-go/usage`. It caches for 60 s; TTL, URL and timeout are config. Any HTTP or parse failure shows "unavailable".
- The session id is a persisted UUID in `~/.local/state/agent-hub/opencode-session-id`.
- The key resolves through the existing `get_env_api_key("opencode-go")`: `OPENCODE_API_KEY`, then the Agent Hub credential store. At the owner's request the Pi key was copied into the encrypted credential store (never printed). After a restart, the live route returned 0% / 7% / 3%, matching a direct GET.
- OpenCode Go is listed in Settings → LLM Providers as a key-only provider (`99b46aa58`): it accepts a key but never routes workloads, like TypeSafe.

## Owner items
- Checked by the owner: "Extra usage" is off, and the workspace already allows Global regions.
- The workspace has $0 credits and no auto-recharge, so the key can't spend beyond the Go plan.
- Lock-down options for the `Pi-Go` key were reviewed in the console (the key currently has full workspace permissions); changes are pending owner approval.

## Cost of this work
Measured from transcripts (deduplicated by message id), priced at Agent Hub `model_catalog.json` rates (Opus 5.5 $4/$20, cache read $0.20 / write $5; Sonnet 5.5 $2/$10, $0.10 / $2.50 per M), API-equivalent:

| Part | Input / cache write / cache read / output | Cost |
|---|---|---:|
| Subagents, Opus 5.5 (removal and Pi fixes, quota feature) | 242 / 244,343 / 6,991,402 / 54,267 | $3.71 |
| Subagents, Sonnet 5.5 (three audits) | 322 / 315,843 / 21,404,764 / 74,986 | $3.68 |
| Coordinator session (Opus 5.5) | 194 / 199,343 / 14,463,809 / 80,083 | $5.49 |
| Smoke-check subjects (OpenCode Go, native-reported) | see results.json | $0.0013 |
| **Total** | | **about $12.88** |

The planned estimate was $5–12, so this came in just above it. The removal-and-fixes agent was the largest single item: it ran long because of UI rework and a full Pi replay. Subscription cash charges were not measured.
