# Claude Orchestrated Worker Examples

Use these with `backend/scripts/run_claude_orchestrated_worker.py`.

## Known-good smoke runs

Direct worker:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --prompt-file backend/scripts/claude_orchestrated_worker_examples/smoke_direct_prompt.md \
  --allowed-tools Read \
  --timeout-seconds 60
```

Delegated subagent worker:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --prompt-file backend/scripts/claude_orchestrated_worker_examples/smoke_subagent_prompt.md \
  --agents-file backend/scripts/claude_orchestrated_worker_examples/readonly_subagent_agents.json \
  --allowed-tools Agent \
  --timeout-seconds 90
```

## Observability

The wrapper emits these early on stderr:

- `ARTIFACT_DIR`
- `METADATA_PATH`
- `CLAUDE_PID`
- `SESSION_ID` once Claude emits init
- `TRANSCRIPT_PATH` once the transcript exists on disk

Artifacts:

- `run.json`: wrapper summary and final status
- `stdout.jsonl`: raw Claude `stream-json` output
- `stderr.log`: Claude stderr

Additional traces:

- Claude transcript JSONL: `~/.claude/projects/.../<session-id>.jsonl`
- Agent Hub session events: `st session-events <session-id>`

## Current limitation

The richer structured file-reading prompts in `readonly_*` are useful for experiments, but they are not yet reliable as a default harness. The stable proof-of-concept path today is:

- simple prompt contract
- optional custom agent spec JSON
- transcript-based observability
