# Canonical context adapters

Agent Hub owns shared context selection, ordering, authority, provenance, and
failure semantics. TUI integrations in this directory are transport adapters
only: they call `agent-hub-context deliver`, validate
`agent-hub.context.v1`, preserve the harness's native system/safety prompt, and
write immutable per-delivery JSON and Markdown artifacts.

External delivery is supplemental and fail-open. If Agent Hub, its contract, or
its immutable artifacts are unavailable, the adapter emits a visible degraded
warning, preserves the original native argv/request/system context, injects no
failure text, and records no successful preinjection claim. This does not weaken
the canonical assembler's internal contract validation; it prevents an external
context dependency from blocking the native model.

Supported adapters are Claude Code, Codex, Pi, and Antigravity CLI.
Claude and Codex receive additive launch context; Pi appends it in
`before_agent_start`. Antigravity uses a native
always-on rule that asks the agent to retrieve canonical context through its
shell. Retrieval requires the native command permission. It is not automatic
system-prompt injection. All shell-capable adapters declare `bash` for guidance
selection; this declaration grants no execution permission.

Claude's launcher exposes one unique immutable additional directory whose
`CLAUDE.md` contains the exact canonical bytes; Claude preloads that file for
the parent and spawned agents. Codex's launcher uses additive
`developer_instructions` for fresh threads. These launch channels preserve full
payloads that each TUI otherwise spills from native hook output into truncated
previews. Their native SessionStart/SubagentStart hooks only bind the immutable
launch artifact to real session/subagent IDs, preventing a second context copy.

OpenCode, Hermes CLI, Claude GPT, and Gemini CLI are retired. Historical delivery metadata
and saved sessions remain readable. The installer removes the old Claude GPT
launcher/settings links; it does not revive retired clients.

Codex 0.153.4 restores saved developer instructions on both resume and fork and
ignores a fresh override, even when the override is passed to the consuming
subcommand parser. For those two commands the wrapper therefore warns, preserves
the raw native invocation and saved thread context, and deliberately creates no
fresh Agent Hub delivery or binding claim. This avoids falsely claiming that a
new payload reached the model.

Pi declares shell capability only while its `bash` tool is active. Starting Pi
with `--no-tools` or a read-only tool selection retains shared policy without
requesting shell command guidance.

Install all supported adapters:

```bash
python3 integrations/context-delivery/install.py
```

Install or verify one surface:

```bash
python3 integrations/context-delivery/install.py --surface antigravity
python3 integrations/context-delivery/install.py --surface antigravity --check
```

The installer uses source symlinks rather than copies. Active adapter code
therefore cannot diverge from the checked-in implementation. Delivery evidence
is stored below `~/.local/state/agent-hub/context-deliveries/` in immutable,
session-scoped files. Token counts are diagnostic only. Once Agent Hub has
rendered a delivery contract, neither the client nor the installer imposes a
hard full-payload ceiling, rejects or truncates that payload for size, or drops
required policy. The canonical upstream assembler may still select optional
references by semantic relevance, reference limits, and render tier; that is
context selection, not transport-side payload trimming. Before changing a
home-owned settings file, the installer writes one unique read-only backup; an
idempotent install does not create backup churn.

Claude's context wrapper lives at `~/.claude/bin/claude`; the native installer
owns `~/.local/bin/claude`. The wrapper follows that updater-managed launcher
on every invocation, so `claude update`, version checks and new sessions use
the same installation. `CLAUDE_REAL` remains an explicit override, and the npm
binary is a fallback for npm installations. A link back to the context wrapper
is skipped to prevent recursion. The installer retires the obsolete
`claude-real` alias, which stayed pinned when the native updater advanced.

The client applies a 15-second subprocess deadline because an unbounded local
CLI child can otherwise hang a native TUI hook and survive as an orphan. Set
`AGENT_HUB_CONTEXT_TIMEOUT_SECONDS` when a slower local deployment needs a
different operational deadline; this does not alter or trim the payload.

## Delivery evidence

A successful descriptor records `evidence_stage: generated`: canonical bytes and
immutable artifacts exist. A native lifecycle binding records `bound`: those
artifacts are associated with a native session ID. Neither proves model receipt.
Only inspection of an actual provider request can establish observed delivery.
Aico's independent probe reports availability, never current-session injection.
Antigravity tool execution establishes retrieved context. Codex resume/fork uses
saved native context and makes no fresh-delivery claim.

To check a shared UI policy change, render a fresh `agent-hub-context deliver`
contract for each supported surface with the same product UI task and verify the
selected prompt revision in its blocks. Also run the installer with `--check` to
verify each native adapter is present. These checks establish generation and
adapter installation only; record binding, retrieval, provider delivery and
actual agent behavior separately. The Agent Hub DB owns the activation prompt,
the central skill owns the review procedure, and SlopMiner's scoped guides own
approved design direction. This adapter does not duplicate those instructions.

Optional project index, tool guide, and continuity diagnostics distinguish
included, inapplicable, and unavailable components. Optional failures do not
silently discard required shared policy. A failed required assembly remains a
failed contract, even though external native launch continues.

Antigravity's installed CLI stores imported plugins below `~/.gemini/config/`
(verified with `agy plugin install` and `agy plugin list`). The installer keeps
its native import registration and links the rule and manifest to these sources.
The public plugin documentation currently lists a different staging path; the
installed client and an actual retrieval test determine this adapter's layout.

### Pi session ingestion

The Pi extension uses the native session UUID for ingestion and retains the Aico
session ID as correlation metadata. It syncs the JSONL transcript on session start,
agent start/end, and shutdown through `agent-hub-context-client sync-pi` and the
existing canonical ingestion service. The same source-linked installer provides
the extension: `python3 integrations/context-delivery/install.py --surface pi`;
use `--home PATH` for an isolated installation and `--check` to verify it.

Pi's selected provider/model is stored separately in `pi_selection`. Assistant
messages retain Pi's native provider/model label; these labels do not establish
that a remote server used that model. Native response usage feeds the existing
session usage rollup, including nested usage on tool-result messages without
inventing a model attribution for those calls. Input includes Pi's input, cache-read and cache-write counts;
output and cached input remain separate. Native costs are retained as evidence,
not recomputed or inserted into a second cost ledger. Error responses with zero
usage stay zero. A fork's copied parent entries are excluded from fresh ingestion.
If its parent transcript cannot be read inside the configured native roots, sync
fails visibly rather than charging inherited history again.

`AGENT_HUB_PI_SESSIONS` overrides Pi's native session directories;
`AGENT_HUB_TRANSCRIPT_ROOTS` still replaces all transcript roots. Sync never calls
a model or changes credentials. Failures preserve native Pi input and context.
Live delivery and authenticated model readiness require separate runtime evidence.

### Explicit Pi Daybreak and optional context

Tether can select `--tool pi --model openai/gpt-6-sol --reasoning-effort xhigh
--daybreak on`. The extension reads the per-launch `AICO_ROOT_MODEL` and
`AICO_ROOT_DAYBREAK` metadata, registers the native public OpenAI provider, and
decorates both model getters with `samplingParams.access_programs.cyber` for the
selected Responses model. True requests `daybreak_blue`; false requests
`standard`. An omitted switch registers no provider override. Native auth,
streaming, filtering, refresh, and other models remain owned by Pi. The model
metadata reaches main, nested, and compaction requests without relying on a
main-agent request hook. Native Pi 1.4 encodes `--thinking xhigh` in a
`configuration_update.reasoning.effort` item while the top-level request effort
is `medium`; the extension preserves that native model behavior. See the [OpenAI Daybreak guide](https://developers.openai.com/api/docs/guides/daybreak)
for project/model approval and explicit program errors.

`--agent-hub-context off` in Tether sets `AICO_ROOT_AGENT_HUB_CONTEXT=false` for
that Pi session. The extension still requests canonical delivery, using
`--optional-context off` on the shared client/CLI. That mode maps the existing
reference, reference-index, project-index, tool-guidance and continuity selectors
to false. It omits nonrequired advisory prompts and memories while retaining
required global/project sources, mandates and guardrails. Native Pi/project
instructions and lifecycle transcript ingestion are unaffected. This compares
optional injection with required policy retained; it does not claim zero Agent
Hub bytes. Default/on behavior is unchanged.

The installer command above remains the supported installation/check route.
Integrate both Tether and Agent Hub changes before a managed Tether reload, then
start fresh Pi sessions or use Pi's native extension reload. No credentials or
global `models.json` changes are needed. Synthetic tests intercept native
Responses requests in memory and check program/effort for main, nested and
compaction calls, plus policy preservation and ingestion. The optional installed
Pi transport check skips when the managed Pi runtime is absent; it never calls a
remote provider. A harmless authenticated request and live delivery observation
are separate owner-run qualifications.


### Fixed native session work roles

Tether root creation supplies `ST_WORK_ROLE`, `ST_WORK_ROLE_SOURCE`, and an
optional `ST_WORK_ROLE_DISPLAY_NAME` from immutable root creation metadata.
The existing Codex and Claude `bind` SessionStart hook projects that declaration
through `bind-native-work-role` and canonical ingestion to the hook's actual
native UUID. This registration runs even when supplemental context binding is
unavailable. SubagentStart, child markers, and known native children do not
inherit the root declaration. Logical Aico IDs remain provenance only.

Pi's existing `sync-pi` route forwards the same declaration with its native
session UUID. The extension and its provider import remain unchanged. Canonical
upsert owns validation, first declaration, same-role retry and different-role
conflict. A resumed native UUID keeps its first role and provenance. No polling,
role database, title inference, prompt addition or per-command telemetry is added.
Without explicit launch metadata or a supported native UUID, the session remains
Unknown. Direct launches and legacy owner widgets are therefore undeclared.

Integrate these producers with the Agent Hub work-role DTO/immutable-upsert
checkpoint and Tether launcher checkpoint. Rebuild through the existing managed
services and verify the installed context-adapter source links before launching
a fresh root with `st aico create ... --work-role implementation`. Existing
processes need their normal native resume/extension reload before using updated
producer code; no live activation or deployment is performed by this checkpoint.

### OpenCode v2 native free models

Install the source-linked plugin and launcher with
`python3 integrations/context-delivery/install.py --surface opencode`.
Tether exposes `opencode-deepseek-free` and `opencode-glm-free` as ordinary Aico
and A-Term tools. The launcher resolves the official CLI on PATH or under
`~/.opencode/bin`, uses its authenticated service, and allocates native sessions
with `opencode api session.create` before launching `mini --model`.

The [v2 plugin context hook](https://opencode.ai/v2/docs/build/plugins) appends the
canonical contract to the native system instructions before each main agent
model request. The adapter stores the exact delivery artifact and uses native
session get/context APIs after idle to ingest completed messages. Orderly launcher
exit also syncs a native session export. Context and sync failures are visible;
OpenCode retains its native session for later export. The adapter never reads
credentials, sets provider headers, or substitutes inference endpoints.

Selection is retained in `opencode_selection`; completed assistant model labels
and message token/cost fields are separate native evidence. Native labels are not
independent proof of the upstream model. Response input includes uncached input,
cache reads and cache writes; the original native fields remain retained. Stable
message identities make repeat sync idempotent. Tether root resume and crash catchup are not yet implemented; child/fork exports fail closed for accounting.
Resume requires an exact `--session`; continue-last and fork through the launcher
are rejected because they can change the identity being recorded.

The [official model list](https://opencode.ai/v2/docs/console/models/) identifies
`opencode/deepseek-v4.1-flash-free` and `opencode/glm-5.3-flash-free` as free for a
limited time. Paid IDs without `-free` are separate selections. Runtime evidence
is retained in `docs/evaluations/opencode-native-20261022/`.
