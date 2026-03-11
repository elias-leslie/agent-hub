# Jenny Model Benchmark

This benchmark profiles Jenny against a fixed seven-model roster:

- `codex/gpt-5.4`
- `codex/gpt-5.3-codex`
- `codex/gpt-5.3-codex-spark`
- `codex/gpt-5.2`
- `claude-opus-4-6`
- `claude-sonnet-4-6`
- `claude-haiku-4-5`

Direct `openai/*` models are excluded from the default roster in this environment because no OpenAI API key is configured; `codex/gpt-5.2` fills that comparison slot instead.

## Goal

Measure Jenny on real governance-style work instead of static catalog scores alone.

The battery focuses on behaviors Jenny is expected to get right:

- dispatch a ready task
- avoid same-task duplicate dispatch
- block closeout when cleanup is pending
- wait on quiet-but-healthy sessions
- reconcile genuinely stalled sessions
- inspect workspace files with tools before deciding
- use `precision_code_search` for real code-navigation lookup when the task calls for it

## Runner

Use:

```bash
python backend/scripts/run_jenny_model_benchmark.py --dry-run
python backend/scripts/run_jenny_model_benchmark.py \
  --runs-per-case 3 \
  --project-id agent-hub \
  --output-json /tmp/jenny-benchmark.json \
  --output-md /tmp/jenny-benchmark.md
```

Defaults:

- project id: `agent-hub`
- attempt order: shuffled with seed `42`
- temp workspaces: `backend/.tmp/jenny-model-benchmark`
- client id: auto-resolved from `AGENT_HUB_CLIENT_ID` or the first active local client with access to the target project

The live Precision Code Search benchmark case requires an indexed real project context. It is included in the default battery, so the default benchmark project is now `agent-hub` rather than `persona-sandbox`.

## Scoring

Each attempt records:

- latency
- input/output/total tokens
- turns
- tool call count
- tool names used from `session_events.tool_name`
- structured decision correctness
- infra failure vs model failure classification

Composite score:

- 85% decision correctness
- 15% tool-use compliance for tool-required cases

Tool-use compliance now supports specific-tool enforcement. Generic workspace cases still only require that some tool was used. Precision coverage can require the exact `precision_code_search` tool name, and a correct JSON answer still fails if that tool was not used.

Infra failures are tracked separately so transport problems do not get mistaken for model-quality regressions.
