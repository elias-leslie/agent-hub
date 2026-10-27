# Multi-model workflow evaluation — plan (27 October 2026)

Task `task-0f7217aa26c145a3`. Simple on purpose: one script, five runs, one table.

The previous harness test spent far more on coordination than on the runs it measured: about $4 for the agent coordinating and accounting, $0.27 on pilot runs it threw away, and $0.87 on the runs themselves. This test avoids that. No agent is involved while it runs, there are no observers or context-freezing, and there are no extra accounting documents.

## Task

Reuse the small frozen coding fixture and its independent 16-check `acceptance.py` from [harness-efficiency-20261022](../harness-efficiency-20261022/). One run costs a few cents and passing or failing is objective.

## Runs

`run.py` runs these one after another and then prints the table. That is the whole test.

| # | Run | Answers |
|---|---|---|
| 1 | Claude Code (Opus 5.5), its own tools, headless | Claude Code's efficiency and effectiveness |
| 2 | Codex (gpt-6.1-sol) | Same, for Codex |
| 3 | Pi (gpt-6.1-sol) | Same, for Pi; matches the Codex model, so this isolates the harness |
| 4 | Workflow: implement on Claude Code → review/fix on Codex | What a handoff costs compared with runs 1 and 2 |
| 5 | Workflow: Claude Code step with a refusal injected after turn 1 → the agent chain takes over | Whether takeover keeps the work, and how long it takes |

Run 5 uses the executor's test hook to inject the refusal. We don't try to provoke a real safety classifier.

**Repeats:** only if two of runs 1–3 come within 15% of each other on tokens or time. In that case those two arms run once more, and that's the limit.

## Table columns

All taken straight from each harness's own output:
- Claude: `result.usage` and `modelUsage`
- Codex: `turn.completed.usage`
- Pi: `message_end.usage`

| Column | Meaning |
|---|---|
| passed | checks passed out of 16 (`acceptance.py`) |
| input / cache read / cache write / output | tokens, never double-counted |
| cost | the tokens above × catalog price (API-equivalent) |
| Claude limit used | change in five-hour utilisation, from `rate_limit_event` (coarse: 1-point steps) |
| wall time | seconds |
| tool calls (failed) | from the harness's own events |
| answered by | the model that actually answered, according to the harness output |

For runs 4 and 5, also record:
- the handoff packet size;
- the lines step 2 rewrote in files step 1 had already completed;
- the seconds from the refusal to the next model's first turn;
- whether the worktree was kept.

## Limits

- **Claude Code only runs Opus on a subscription,** so run 1 compares whole setups, not the harness alone. Runs 2 and 3 are the harness-only comparison.
- **One small fixture is descriptive,** not a benchmark. The long-session cost question was already settled by the Phase 0 measurement: per-turn cache writes fell from about 800–1,000 tokens and growing to about 80–160.

Done when the table is in `README.md` here, with the raw harness outputs kept beside it.
