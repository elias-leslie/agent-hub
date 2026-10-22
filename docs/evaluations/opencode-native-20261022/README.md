# Native OpenCode free-model integration — 2026-10-22

Both free models succeeded in real ordinary Aico windows through OpenCode v2.1.3.
The authenticated native CLI supplies inference; Agent Hub supplies additive
canonical context and retains native session, response-model and usage evidence.

| Model | Aico session | Native session | Reply | Native time | Native cost |
| --- | --- | --- | --- | --- | --- |
| `opencode/deepseek-v4.1-flash-free` | `7814484b` | `ses_e9a32f59bffeLzAjSovodPrTwt` | `AICO_DEEPSEEK_OK` | 5.6 s | $0 |
| `opencode/glm-5.3-flash-free` | `90abd5cf` | `ses_e9a32e487ffehYT3F5I5qNJlHv` | `AICO_GLM_OK` | 6.0 s | $0 |

The exact selected ID matches each completed native assistant model label.
DeepSeek reported 85 uncached input, 12,800 cached input and 8 output tokens;
GLM reported 12,474 input and 7 output tokens. Agent Hub retained one user event,
one assistant event and one usage event per session. Repeating each native export
sync appended zero events and skipped all three existing events.

Both context artifacts report `ok`, with payload hash
`acdc5385522ffc243d2092a64a68a7d58200eaefd908965b9fd1b30fd611d32b` and 19,602
rendered characters. [results.json](results.json) records the immutable local
artifact paths, native token fields, model variants and timing evidence without
copying private context or authentication data.

Observed local overhead: one canonical context delivery took 2.301 seconds;
repeat ingestion took 2.427 seconds (DeepSeek) and 2.424 seconds (GLM). Native
export took 51 and 53 milliseconds. These are single local measurements, not a
latency distribution or a complete cold-start benchmark. The native 5.6/6.0-second
turn measurements include context delivery before inference. The adapter adds no
model request to select context or ingest evidence.

Tether source `f1cd32d7d4557df076637969ecce06ae4c345874` passed 307 tests and its
managed rebuild `0799e37c6fca4d29aa6d8b2e8d7945a2` succeeded. Agent Hub integration
source is `218d695ac2dc2c1f11b9b3a99f35bdecfaa1fd9a`. Focused adapter/accounting
checks passed 9 tests; the changed-source gate passed 52 tests plus types,
formatting and security checks. Full acceptance identified two shared fixture
harness-option lists requiring the new OpenCode option; those fixtures are updated
with this report. The final managed deployment receipt is reported separately.

## Supported path and evidence limits

OpenCode's [CLI documentation](https://opencode.ai/v2/docs/cli/commands/) documents
`mini --model`, `run --format json`, session APIs and export. Its
[plugin API](https://opencode.ai/v2/docs/build/plugins) supplies the additive
`session.hook("context")`, `session.wait`, `session.get` and `session.context`
interfaces. Its [model list](https://opencode.ai/v2/docs/console/models/) identifies
both exact free IDs and describes free availability as limited time.

The launcher resolves `opencode` on PATH or the official `~/.opencode/bin/opencode`
installation and creates a session through `opencode api session.create`. Native
session allocation matters: locally accepted arbitrary session IDs returned
free-tier 403 errors, while native-created IDs succeeded. One standalone-mode
probe also returned 403. These observations do not establish the server's reason;
the shipped launcher uses the successful authenticated service mode and native
allocation. It supplies no custom identity headers or provider routing overrides.
The earlier direct-provider rejection recorded in
[the Pi evaluation](../pi-opencode-20261022/README.md) remains valid for that path.

Native model labels do not independently verify the upstream backend model.
Child/fork accounting fails closed, Tether root resume and crash catchup are
unsupported, and Tether's OpenCode activity indicator remains `unknown`. The native
UI, successful native outcome and recorded usage are independent retained facts.
