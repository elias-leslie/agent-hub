# Persona Arena Benchmark

This benchmark profiles the persona against a fixed seven-model roster:

- `codex/gpt-5.4`
- `codex/gpt-5.3-codex`
- `codex/gpt-5.3-codex-spark`
- `codex/gpt-5.2-codex`
- `claude-opus-4-6`
- `claude-sonnet-4-6`
- `claude-haiku-4-5`

Direct `openai/*` models are excluded from the default roster in this environment because no OpenAI API key is configured; `codex/gpt-5.2` fills that comparison slot instead.

`xai/*` models stay out of the default roster on purpose. They are useful candidate cohorts, but they spend real API dollars and should be run as opt-in Arena comparisons instead of every baseline pass.

## Goal

Measure the persona on real governance-style work instead of static catalog scores alone.

The battery focuses on behaviors the persona is expected to get right:

- dispatch a ready task
- avoid same-task duplicate dispatch
- block closeout when cleanup is pending
- wait on quiet-but-healthy sessions
- reconcile genuinely stalled sessions
- inspect workspace files with tools before deciding
- use `precision_code_search` for real code-navigation lookup when the task calls for it
- use the shared public-web research stack when external validation is required

## Runner

Use:

```bash
python backend/scripts/run_persona_model_benchmark.py --dry-run
python backend/scripts/run_persona_model_benchmark.py \
  --runs-per-case 3 \
  --project-id agent-hub \
  --output-json /tmp/persona-benchmark.json \
  --output-md /tmp/persona-benchmark.md
```

Defaults:

- project id: `agent-hub`
- attempt order: shuffled with seed `42`
- temp workspaces: `backend/.tmp/persona-model-benchmark`
- client id: auto-resolved from `AGENT_HUB_CLIENT_ID` or the first active local client with access to the target project

Cheap xAI comparison example:

```bash
python backend/scripts/run_persona_model_benchmark.py \
  --models codex/gpt-5.4,claude-sonnet-4-6,xai/grok-4.20-reasoning \
  --runs-per-case 1 \
  --cases dispatch-ready,wait-healthy-session \
  --no-persist
```

Use `xai/grok-4.20-multi-agent` only for narrow research/profile experiments, not routine governance baselines. It is responses-only, more latent, and can consume meaningfully more tokens than the single-agent roster.

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

Ranking and experiment tie-breaks:

- correctness and pass rate stay primary
- when those are tied or statistically non-inferior, fewer tool calls win before token and turn count
- infra-only failures are excluded from those efficiency aggregates so broken transport does not masquerade as efficiency

Tool-use compliance now supports specific-tool enforcement. Generic workspace cases still only require that some tool was used. Precision coverage can require the exact `precision_code_search` tool name, and a correct JSON answer still fails if that tool was not used.

Infra failures are tracked separately so transport problems do not get mistaken for model-quality regressions.

## Dashboard

Current home:

- `http://localhost:3003/persona/arena`

Placement rule:

- Arena is the umbrella evaluation surface, and the persona gets the first rich view there.
- The backend/storage model should stay agent/model agnostic even when the first rich UX is persona-first.

Why:

- The persona is hidden from the normal Agents section by design.
- Most benchmark-driven tuning decisions are currently about the persona's prompts, model assignment, heartbeat harness, and supervisory behavior.
- The storage and API need to be reusable for other agents later, but the first operator UX should match where the persona is already managed.

## Lean Plan

Current state:

- benchmark runs, attempts, config snapshots, and open regression clusters are now persisted
- repeated baseline-vs-candidate experiments are now tracked as first-class records
- the Arena runtime/overview surface renders benchmark KPIs, trendlines, recent runs, open regressions, and model performance
- the Arena experiments view renders benchmark experiment status, decision, and cohort deltas
- one-shot benchmarks and honing iterations can write into the same history model
- Persona heartbeat now has a bounded supervisor completion-review stage after deterministic residue checks, so “false complete” behavior can be measured and corrected without a second open-ended loop

Next tasks:

1. Keep Arena as the primary persona benchmark dashboard.
2. Add benchmark run drill-down from Arena into per-attempt detail and failure-cluster history.
3. Add controlled A/B workflow support:
   - fixed `suite_id`
   - baseline vs candidate labels
   - enough repeated runs to compare changes statistically instead of reacting to a single run
   - conservative promote/hold/rollback decisions with visible reasons such as `underpowered`, `mixed_config`, or `candidate_underperforms_baseline`
4. Add explicit rollout/rollback rules for persona prompt and model changes:
   - no prompt/model adoption without benchmark comparison against the last known-good baseline
   - auto-flag regressions when a candidate underperforms baseline on the same suite
5. Extend the benchmark suite beyond current persona supervision cases where needed:
   - long-running patience/focus
   - closeout completeness
   - supervisor completion-review quality (`false_complete`, `false_continue`, `residue_catch_rate`)
   - self-honing quality
   - model assignment review
6. Add a thin operator CLI only if needed after real usage:
   - list suites
   - show latest runs
   - compare baseline vs candidate
   - print open regression clusters
7. Add a global benchmark index later, only when cross-agent comparison becomes valuable enough:
- keep agent-local UX first
- add global rollup after multiple agents have real suites

Scope rule:

- platform: agent/model agnostic
- benchmark content: persona first
- UI: Arena first, global rollup later

## Closed Loop

The persona should not "improve itself" by free-form prompt edits alone.

The intended loop is:

1. detect recurring failure clusters from persisted regressions and benchmark history
2. form one small hypothesis tied to a measured gap
3. run repeated `baseline` vs `candidate` benchmark cohorts on the same suite
4. keep the change only when the experiment decision and evidence support promotion
5. otherwise hold or roll back and keep the regression cluster open

Second-opinion models can help, but they should be experiment cohorts or reviewers, not silent scorers.

Example:

- baseline supervisor model: `codex/gpt-5.4`
- candidate supervisor model: `claude-opus-4-6`
- same benchmark suite
- repeated runs until the comparison is powered enough to decide

Completion-review models should use the same pattern:

- baseline reviewer model: current `supervisor` agent primary model
- candidate reviewer model: alternate reviewer primary model
- same completion-review suite
- repeated runs until the reviewer decision is powered enough to decide

Memory policy experiments should use the same Arena workflow instead of a separate tuner:

- keep the benchmark suite fixed
- run `baseline` vs `candidate` cohorts with `--memory-variant-override`
- compare the cohorts through the existing experiment records and promote only when the evidence supports it
