# Context governance evaluation, 2026-09-19

Jev is available as an opt-in screening tool. These results do **not** qualify automatic policy changes or default semantic screening. Source eligibility, exact duplicates, concurrency checks and delivery assembly remain deterministic.

## Evidence retained

- `jev-heldout-v1.json`: frozen 13-case developer-labelled synthetic holdout, registered before the first dispatch. Twelve Jev judgments plus one deterministic duplicate matched all 13 labels. Usage-priced cost: $0.000379134. A cache replay required no new calls.
- `jev-semantic-packet-repeat-v1.json`: repeat after removing display identifiers from the semantic packet and normalizing pair order. Again 13/13, $0.000363090, zero new replay calls. This is reuse of the original cases, **not** an independent holdout.
- `curator-runtime-receipt.json`: actual canonical memory-curator call, supplied exact source revisions, valid response, no source mutations. The selected safety/narration pair produced no findings. This verifies the route and schema, not sensitivity to every conflict.
- `native-runtime-exploratory-v1.json`: actual fresh native Codex executions using the `coder` agent's catalog model, preserved native instructions, canonical delivery artifacts, read-only tools and full usage events. All six answers were checked against the cited implementation and were correct for the requested inspections.

The native comparison used identical task questions and delivery settings, with Security Research explicitly activated only in the counterfactual. It does not reconstruct every historical prompt in the screenshot. Three cases ran once in each condition; order alternated. The checkout was being finalized during the run, so these are exploratory observations, not a controlled performance qualification. The repeatable runner now fingerprints the source checkout and retains failures if it changes.

| Observed total across three cases | Scoped | Research active |
| --- | ---: | ---: |
| Generated startup tokens per case | 3,925 | 6,009 |
| Total input tokens, including cached | 1,840,118 | 1,020,068 |
| Cached input tokens | 1,674,240 | 839,680 |
| Uncached input tokens | 165,878 | 180,388 |
| Output tokens | 10,931 | 9,066 |
| Elapsed seconds | 253.80 | 216.19 |
| Shell command calls | 56 | 46 |
| First command used prescribed ST search | 0/3 | 1/3 |
| Commands returning nonzero | 1 | 2 |
| Correct requested answer | 3/3 | 3/3 |
| Operator interventions | 0 | 0 |

The startup reduction was 2,084 estimated tokens in this comparison. Total tokens and latency were mixed, with one long scoped inspection. A nonzero search can mean no matches; it does not alone establish a bad tool call. Commands and final answers are retained. There is no objective minimum-call oracle, so an exact unnecessary-call count remains unknown. This small experiment provides no reliable overall performance benefit, regression rate, or general coding-success claim.

Configuration binding and native tool/usage events were observed. Hidden system instructions and exact provider request bodies were not observed. The experiment cannot prove that the model attended to every supplied instruction.

## Source-frozen repeat

`native-runtime-frozen-v1.json` retains a fresh repeat registered with a fingerprint of every relevant source/test file. All six runs verified that the checkout remained unchanged. All six final answers were inspected and correct for the requested read-only inspections. The same canonical startup payload sizes were used. Later review-eligibility and catalog-display fixes are outside this measured snapshot.

| Observed total across three cases | Scoped | Research active |
| --- | ---: | ---: |
| Total input tokens, including cached | 658,683 | 991,053 |
| Cached input tokens | 570,752 | 821,120 |
| Uncached input tokens | 87,931 | 169,933 |
| Output tokens | 8,530 | 9,095 |
| Elapsed seconds | 185.71 | 207.65 |
| Shell command calls | 38 | 48 |
| First command used prescribed ST search | 0/3 | 1/3 |
| Commands returning nonzero | 1 | 4 |
| Correct requested answer | 3/3 | 3/3 |
| Operator interventions | 0 | 0 |

The one initial ST search returned nonzero; tool-family choice alone did not establish a successful first call. Other failures included searching nonexistent `src`/`tests` directories. Scoped totals improved in this repeat, but the exploratory totals were mixed. Three tasks with one run per condition do not establish a reliable effect or a general coding-success rate. Subscription cost allocation and exact cache pricing are unknown, so no billed-dollar native comparison is claimed. Both favorable and adverse results remain retained.

`delivery-scope-receipt.json` separately verifies the canonical CLI: Security Research is absent for global, Agent Hub and Neri context, present in its own project, and present in Agent Hub only when its workflow is explicitly activated. That is generated delivery evidence, not proof of native model receipt.

## Neri experience used

Reviewed the existing Neri TypeSafe preflight continuation results, comparison summary, dispatch/dedup receipt, and the recorded Jev learning (`M:c35555c9`). Its fresh native comparison was 11/11 versus Jev 10/11: Jev confidently treated absent/out-of-scope evidence as a contradiction. A narrower corrected question fixed that case, but was not a new holdout. Broad filtering retained all 18 candidates, showing no demonstrated efficiency benefit. Native responses also invented memory identifiers, so apparent recall did not prove consumption.

Consequently this implementation uses narrow typed pair classification, explicit `unknown` for missing evidence, canonical eligibility before screening, immutable source evidence, and optional human-reviewed remedies. It uses its own durable semantic cache and accounting; it neither borrows Neri's pilot budget nor changes Neri's workflow. Confidence is not permission, proof of usefulness, or authority to rewrite a source.

## Repeating the evaluations

From the repository root, the scripts support a read-only estimate/registration preview unless `--execute` is supplied:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m scripts.evaluate_context_review --model jev-1.13.0 --output /tmp/context-screening-estimate.json
PYTHONPATH=backend backend/.venv/bin/python -m scripts.evaluate_context_runtime --agent coder --output /tmp/context-runtime/results.json
```

Use a stable checkout and a new output path for a new executed cohort. Never overwrite earlier adverse results. The native runner resolves its model from the named agent and catalog; the Jev runner checks the catalog's typed capability and window. Neither invents a spending ceiling, retries an uncertain paid judgment, or changes qualification automatically. Full native transcripts stay local alongside the chosen output; inspect them before sharing. A production default would need a new independent held-out evaluation and representative repeated task outcomes, including misses, total costs, latency and operator effort.
