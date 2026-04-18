# Claude Orchestrated Worker Examples

Use these with `backend/scripts/run_claude_orchestrated_worker.py`.

## Preferred automation path

Use `--spec-file` for real work. The spec keeps the task contract structured while the wrapper still generates the stable plain-text Claude prompt underneath.

Task-driven SummitFlow refactor:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id summitflow \
  --task-id task-715ee872 \
  --task-root /srv/workspaces/projects/summitflow \
  --claim-if-needed \
  --timeout-seconds 900
```

This path:

- runs `st context <task-id>`
- claims the task automatically if you pass `--claim-if-needed`
- switches to the claimed checkout
- builds a write-capable Claude contract from the task description, done-when gates, context target paths, and discovered related tests
- injects a single read-only analysis subagent before the main edit pass

Direct spec:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --spec-file backend/scripts/claude_orchestrated_worker_examples/exact_file_direct_spec.json \
  --timeout-seconds 90
```

Delegated spec:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --spec-file backend/scripts/claude_orchestrated_worker_examples/exact_file_subagent_spec.json \
  --timeout-seconds 120
```

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

## Stable real-work pattern

Use a plain-text prompt with an exact file or path scope. Keep the contract narrow and let transcript observability carry the proof.

Direct exact-file read:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --prompt-file backend/scripts/claude_orchestrated_worker_examples/exact_file_direct_prompt.md \
  --allowed-tools Read \
  --timeout-seconds 90
```

Delegated exact-file read:

```bash
PYTHONPATH=backend backend/.venv/bin/python backend/scripts/run_claude_orchestrated_worker.py \
  --project-id agent-hub \
  --workdir /srv/workspaces/projects/agent-hub \
  --prompt-file backend/scripts/claude_orchestrated_worker_examples/exact_file_subagent_prompt.md \
  --agents-file backend/scripts/claude_orchestrated_worker_examples/readonly_subagent_agents.json \
  --allowed-tools Agent \
  --timeout-seconds 120
```

## Observability

The wrapper emits these early on stderr:

- `ARTIFACT_DIR`
- `METADATA_PATH`
- `CLAUDE_PID`
- `SESSION_ID` once Claude emits init
- `TRANSCRIPT_PATH` once the transcript exists on disk

Artifacts:

- `run.json`: wrapper summary, transcript progress, and final status
- `stdout.jsonl`: raw Claude `stream-json` output
- `stderr.log`: Claude stderr

Additional traces:

- Claude transcript JSONL: `~/.claude/projects/.../<session-id>.jsonl`
- Agent Hub session events: `st session-events <session-id>`

## Current limitation

The richer structured file-reading prompts in `readonly_*` are useful for experiments, but they are not yet reliable as a default harness. The stable proof-of-concept path today is:

- plain-text prompt contract
- generated from a small JSON worker spec when automating
- exact file or path scope
- optional custom agent spec JSON
- transcript-based observability
