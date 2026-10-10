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

A subsequent live curator review compared the Safety Directive with the two global owner-mandate memories. Review `ea51fb0c-e6cb-42d9-813a-6960040e7069` identified redundancy but joined non-contiguous source excerpts; the evidence validator rejected the response and retained it without source changes. After making the response schema explicitly require one contiguous quotation per source, review `067feca9-6c71-4e85-9a97-5326f487edac` returned two validated redundancy findings through `memory-curator` on `codex/gpt-5.5`. Both records remain in canonical review history. This is a corrected repeat, not an independent qualification. Regression tests retain rejection of joined excerpts and verify reviewer provenance for rejected responses.

`delivery-scope-receipt.json` separately verifies the canonical CLI: Security Research is absent for global, Agent Hub and Neri context, present in its own project, and present in Agent Hub only when its workflow is explicitly activated. That is generated delivery evidence, not proof of native model receipt.

## Repeating the evaluations

The [autonomous recovery receipt](autonomous-recovery-receipt.json) retains the later production verification: two validated context reviews, eight successfully reviewed memories, rejected recovery assessments, and one idempotent technical task. The live project had automatic task execution disabled, so queue admission did not mean that task ran. Remaining findings and this execution gate are reported honestly; no autonomous live source edit or new Jev qualification is claimed.

From the repository root, the native runtime script supports a read-only estimate/registration preview unless `--execute` is supplied. The Jev screening script was retired with the context screening service; its earlier results remain recorded here.

```sh
PYTHONPATH=backend backend/.venv/bin/python -m scripts.evaluate_context_runtime --agent coder --output /tmp/context-runtime/results.json
```

Use a stable checkout and a new output path for a new executed cohort. Never overwrite earlier adverse results. The native runner resolves its model from the named agent and catalog. It does not invent a spending ceiling, retry an uncertain paid judgment, or change qualification automatically. Full native transcripts stay local alongside the chosen output; inspect them before sharing. A production default would need a new independent held-out evaluation and representative repeated task outcomes, including misses, total costs, latency and operator effort.
