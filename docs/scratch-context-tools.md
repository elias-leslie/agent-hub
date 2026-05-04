# Scratch Context Tools

Agent Hub now keeps oversized direct-tool output out of the model transcript by indexing it as a transient scratch artifact.

## Behavior

- `bash` returns small output inline.
- `bash` indexes output above the inline threshold and returns `SCRATCH_ARTIFACT_INDEXED` with `artifact_id`, byte/line counts, saved-token estimate, and a bounded preview.
- `search_scratch_context` searches one artifact by id or current-session artifacts when no id is supplied.
- `batch_execute` runs up to 8 shell commands sequentially. Small results stay inline; large results become scratch artifacts.

Scratch artifacts are file-backed under `AGENT_HUB_SCRATCH_CONTEXT_DIR` or the system temp dir. They are execution context, not durable memory, and are not automatically captured into Agent Hub memory.

## Agent Flow

Large command:

```json
{"name":"bash","input":{"command":"st check --check"}}
```

Compact result:

```text
SCRATCH_ARTIFACT_INDEXED
artifact_id: scratch_abc123def456
stored: 142391 bytes, 2104 lines, 18 chunks
saved_estimate: 33670 tokens
search: call search_scratch_context with {"artifact_id":"scratch_abc123def456","query":"<term>"}
preview:
...
```

Follow-up:

```json
{"name":"search_scratch_context","input":{"artifact_id":"scratch_abc123def456","query":"FAILED test_tool_loop"}}
```

Batch:

```json
{
  "name": "batch_execute",
  "input": {
    "commands": [
      "git status --short",
      "st search \"DirectToolExecutor scratch\"",
      "st check pytest -- backend/tests/tools/test_scratch_context.py"
    ]
  }
}
```

## Token Math

Context-mode benchmarked 315 KB raw output into roughly 5.5 KB of useful context, about 98% smaller. Agent Hub scratch context uses the same basic economics without adopting context-mode:

- 140 KB command output is about 35K tokens at 4 chars/token.
- A 4 KB preview plus metadata is about 1K tokens.
- Search results are usually under 1 KB, so follow-up retrieval costs hundreds of tokens instead of replaying tens of thousands.
- Batch execution saves extra tool turns and prevents multiple medium logs from accumulating in one transcript.

## Fit With Existing ST Tools

`st search` remains canonical for repo/code lookup. Scratch context handles output that was already produced in the session, such as logs, check output, or generated reports.

`st graph` and Fallow remain canonical for graph/topology and JS/TS audits. Scratch context stores their bulky outputs when a run is needed, then lets agents search the artifact for symbols, files, or warnings.

ST tool functionality stays token-efficient in two layers:

- ST commands produce compact, structured output when possible.
- Scratch context catches overflow when a command still emits too much text.

This means agents do not need to choose between losing raw output and flooding context. They get a handle first, then retrieve slices only when needed.

## Adoption Decision

Do not vendor or run `context-mode` inside Agent Hub. Its useful pattern is adopted as native scratch-artifact behavior:

- Agent Hub owns execution, permissions, project scope, and tool definitions.
- No extra MCP server or hosted-service licensing surface is added.
- Scratch artifacts stay transient and separate from long-term memory.
- The implementation composes with Claude, Codex, Agent Hub direct tools, `st search`, `st graph`, and Fallow instead of competing with them.
