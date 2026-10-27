# Multi-model workflow evaluation (27 October 2026)

Task `task-0f7217aa26c145a3`. Plan: [PLAN.md](PLAN.md). Runner: `run.py` (one script, one pass; raw per-run numbers in `results.json`).
Fixture and 16-check grader: [harness-efficiency-20261022](../harness-efficiency-20261022/). Thinking level "high" on every arm.
Runs 1-3b call the shipped step executors directly; runs 4 and 5 go through the workflow engine (test hooks on for that process only, live service config untouched).

## Results

Tokens are disjoint, from each harness's own usage. Cost = tokens x catalog price (Opus: catalog $4 / $0.20 read / $5 write / $20 out per M; gpt-6.1-sol: the catalog holds credits only, so the pinned $2 / $0.10 / $10 per M schedule from the last evaluation, same ratios). Tool calls are counted from the raw harness events (failed in brackets). Total tokens = sum of the four columns.

| run | passed | input | cache read | cache write | output | total | cost USD | wall s | tools (failed) | answered by |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 Claude Code / Opus 5.5 | 16/16 | 8 | 71,482 | 11,160 | 1,626 | 84,276 | 0.103 | 16.9 | 3 (0) | claude-opus-5-5 |
| 1 repeat | 16/16 | 8 | 71,442 | 11,114 | 1,671 | 84,235 | 0.103 | 16.0 | 3 (0) | claude-opus-5-5 |
| 2 Codex / gpt-6.1-sol | 16/16 | 24,279 | 50,304 | 0 | 832 | 75,415 | 0.062 | 20.2 | 4 (0) | gpt-6.1-sol |
| 2 repeat | 16/16 | 12,321 | 80,128 | 0 | 779 | 93,228 | 0.040 | 22.2 | 5 (0) | gpt-6.1-sol |
| 3 Pi / gpt-6.1-sol | 16/16 | 4,159 | 18,304 | 0 | 853 | 23,316 | 0.019 | 41.9 | 9 (0) | gpt-6.1-sol |
| 3b Agent Hub harness (coder) / gpt-6.1-sol | 16/16 | 6,957 | 43,776 | 0 | 1,270 | 52,003 | 0.031 | 54.3 | 14 (unknown) | gpt-6.1-sol |
| 4 Workflow: Opus implement, Codex review_fix | 16/16 | 17,864 | 216,668 | 17,975 | 2,087 | 254,594 | 0.193 | 41.0 | 9 (1) | Opus, then gpt-6.1-sol |
| 5 Workflow: Opus + injected refusal, chain takes over | 16/16 | 16,508 | 109,965 | 13,467 | 883 | 140,823 | 0.122 | 24.2 | 7 (1) | gpt-6.1-sol (Opus refused) |

Repeat rule: runs 1 and 2 landed within 15% on tokens (10.5%), so those two ran once more; no other pair qualified. Claude five-hour meter: 0.0 points for run 1 (1-point steps, too coarse for a few-cent run); not usable for runs 4 and 5 either. Run 3b's failed-tool count is "unknown" (Agent Hub's result carries calls, not their outcomes).

Runs 4 and 5 detail:

| | run 4 | run 5 |
|---|---|---|
| Handoff packet (step 2 / takeover attempt) | 490 tokens, 1,961 chars (first step 329) | 434 tokens, 1,736 chars, with partial progress (first attempt 329) |
| Lines step 2 rewrote in files step 1 completed | 0 | n/a (nothing was completed before the refusal) |
| Refusal to next model's first event | n/a | 0.3 s (refusal at 5.5 s into the Opus attempt) |
| Worktree kept | yes | yes |
| Per step | Opus $0.139, 18 s, 3 tools; Codex $0.054, 20 s, 6 tools | Opus $0.070 (wasted), 5.5 s, 1 tool; Codex $0.052, 18 s, 6 tools |

## What it settles

- Effectiveness: every harness and both workflows passed 16/16, so on this fixture there is no quality difference to rank; the fixture is too easy to separate them.
- Efficiency, same model (gpt-6.1-sol): Pi used the fewest tokens (23k, $0.019) by a wide margin, Agent Hub's harness next (52k, $0.031), Codex the most and the least stable (75k to 93k, $0.040 to $0.062; its uncached input swung 24k to 12k between identical runs). Agent Hub's harness is slowest (54 s, 14 tool calls vs 4 to 9), i.e. it spends its time on more small calls, not more tokens.
- Claude Code is the fastest (16 to 17 s, 3 tools, extremely reproducible) and the most expensive per run ($0.103 at catalog prices), but that compares whole setups: it is the only harness on Opus.
- Handoff cost: Opus then Codex cost $0.193 against $0.103 (Opus alone) or $0.040 to $0.062 (Codex alone). The review step itself is cheap ($0.054, 490-token packet, 0 lines rewritten, so it did not churn finished work); the rest of the gap is the engine's Opus step costing $0.139 vs $0.103 direct (4 turns instead of 3, 92k cache read instead of 71k, canonical context added).
- Takeover cost: the injected refusal arrived 5.5 s in, after one tool call, so there was nothing to keep; the next model started 0.3 s after the refusal, got the work in a 434-token packet, and passed. Price of the refusal: the $0.070 Opus attempt (mostly a 13.5k cache write) on top of a normal Codex run.

## Caveats and anomalies

- One small fixture, one pass (two for runs 1 and 2): descriptive, not a benchmark.
- Runs 4 and 5 carry the engine's canonical context (system channel, not counted in packet tokens); runs 1 to 3b have none, which partly explains the larger Opus step in run 4.
- Claude Code writes 1-hour cache entries, which Anthropic bills above the catalog write price: the CLI's own list cost for run 4's Opus step is $0.192 against $0.139 at catalog prices. Run 1 would be roughly $0.158 at the same rate.
- The catalog has no USD price for gpt-6.1-sol (credits only); worth fixing so cost_logs show a real figure.
- The refusal in run 5 is the executor test hook, not a real classifier. Opus still ran one real turn first, so its cost is real.
- No product bugs found. Runner-side setup only: credentials had to be hydrated in-process like service startup.
