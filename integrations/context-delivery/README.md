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

The installed surfaces are Claude Code, its Claude GPT transport variant,
Codex, Gemini CLI, and Pi. Claude and Codex receive additive launch context,
Gemini receives it at BeforeModel, and Pi appends it in `before_agent_start`
whenever Pi rebuilds its system prompt.
Claude's launcher exposes one unique immutable additional directory whose
`CLAUDE.md` contains the exact canonical bytes; Claude preloads that file for
the parent and spawned agents. Codex's launcher uses additive
`developer_instructions` for fresh threads. These launch channels preserve full
payloads that each TUI otherwise spills from native hook output into truncated
previews. Their native SessionStart/SubagentStart hooks only bind the immutable
launch artifact to real session/subagent IDs, preventing a second context copy.

Claude GPT is source-owned at `claude-config/bin/claude-gpt` with transport
settings at `claude-config/claude-gpt-settings.json`. Its wrapper merges the
normal Claude settings with the GPT transport settings, labels Agent Hub
delivery with provider `openai` and transport variant `claude-gpt`, and delegates
exactly once to the same canonical Claude launcher. If Agent Hub delivery fails,
that launcher keeps the merged GPT-native argv/settings, warns visibly, and
continues without injecting or claiming supplemental context.

Codex 0.144.5 restores saved developer instructions on both resume and fork and
ignores a fresh override, even when the override is passed to the consuming
subcommand parser. For those two commands the wrapper therefore warns, preserves
the raw native invocation and saved thread context, and deliberately creates no
fresh Agent Hub delivery or binding claim. This avoids falsely claiming that a
new payload reached the model.

Gemini's BeforeModel adapter places the exact canonical text in one stable
leading request message while preserving all original messages and
`config.systemInstruction`. BeforeAgent's
`additionalContext` channel is intentionally not used because Gemini escapes
angle brackets there, which would make model-visible bytes diverge from the
canonical payload hash.

Install all supported adapters:

```bash
python3 integrations/context-delivery/install.py
```

Install or verify one surface:

```bash
python3 integrations/context-delivery/install.py --surface gemini
python3 integrations/context-delivery/install.py --surface gemini --check
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

The client applies a 15-second subprocess deadline because an unbounded local
CLI child can otherwise hang a native TUI hook and survive as an orphan. Set
`AGENT_HUB_CONTEXT_TIMEOUT_SECONDS` when a slower local deployment needs a
different operational deadline; this does not alter or trim the payload.
