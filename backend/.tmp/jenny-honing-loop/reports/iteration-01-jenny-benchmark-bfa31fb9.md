# Jenny Model Benchmark

**Benchmark ID:** `jenny-benchmark-bfa31fb9`
**Project ID:** `agent-hub`
**Models:** `codex/gpt-5.4`
**Cases:** `session_patience_quiet`
**Runs per case:** 1
**Started:** 2026-03-11T18:04:49.609301+00:00
**Completed:** 2026-03-11T18:04:56.023459+00:00

## Ranking

| Rank | Model | Avg Score | Pass Rate | Infra Failures | Model Failures | Avg Latency (ms) | Avg Tokens | Avg Turns | Avg Tool Calls |
|------|-------|-----------|-----------|----------------|----------------|------------------|------------|-----------|----------------|
| 1 | `codex/gpt-5.4` | 78.8 | 0.0% | 0 | 1 | 6409 | 2592 | 1.0 | 0.0 |

## Attempt Details

| Model | Case | Run | Score | Latency (ms) | Tokens | Turns | Tool Calls | Used Tools | Outcome | Detail |
|-------|------|-----|-------|--------------|--------|-------|------------|------------|---------|--------|
| codex/gpt-5.4 | session_patience_quiet | 1 | 78.8 | 6409 | 2592 | 1 | 0 |  | MODEL | wrong_fields: should_dispatch |
