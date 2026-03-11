# Jenny Model Benchmark

This benchmark profiles Jenny against a fixed seven-model roster:

- `codex/gpt-5.4`
- `openai/gpt-5.2`
- `codex/gpt-5.3-codex`
- `codex/gpt-5.3-codex-spark`
- `claude-opus-4-6`
- `claude-sonnet-4-6`
- `claude-haiku-4-5`

## Goal

Measure Jenny on real governance-style work instead of static catalog scores alone.

The battery focuses on behaviors Jenny is expected to get right:

- dispatch a ready task
- avoid same-task duplicate dispatch
- block closeout when cleanup is pending
- wait on quiet-but-healthy sessions
- reconcile genuinely stalled sessions
- inspect workspace files with tools before deciding

## Runner

Use:

```bash
python backend/scripts/run_jenny_model_benchmark.py --dry-run
python backend/scripts/run_jenny_model_benchmark.py \
  --runs-per-case 3 \
  --output-json /tmp/jenny-benchmark.json \
  --output-md /tmp/jenny-benchmark.md
```

Defaults:

- project id: `persona-sandbox`
- attempt order: shuffled with seed `42`
- temp workspaces: `backend/.tmp/jenny-model-benchmark`
- client id: auto-resolved from `AGENT_HUB_CLIENT_ID` or the first active local client with access to the target project

## Scoring

Each attempt records:

- latency
- input/output/total tokens
- turns
- tool call count
- structured decision correctness
- infra failure vs model failure classification

Composite score:

- 85% decision correctness
- 15% tool-use compliance for tool-required cases

Infra failures are tracked separately so transport problems do not get mistaken for model-quality regressions.
