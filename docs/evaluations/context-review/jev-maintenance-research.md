# Jev research applied to context maintenance

Researched 2026-09-19. Sources below are implementations and reports by their authors, not independently reproduced results from our workload. Jev remains optional; these findings do not authorize semantic policy rewrites or qualify a default classifier.

## Concrete outside uses

[Pinecone's Cultivar grader](https://github.com/pinecone-io/cultivar/blob/main/docs/grader.md) offers Jev for rubric-based pass/fail grading and retains its generative grader for explanatory evidence and suggestions. Its published comparison covers only six conversations: agreement on all six, 0.40 versus 6.87 seconds per grade, and estimated cost per thousand grades of $0.63 versus $18.66. That is a useful implementation example, not a reliable general accuracy estimate. The authors describe a previously unequal evidence packet that invalidated a benchmark. We adopt explicit evidence coverage and keep typed labels separate from quoted evidence. We do not copy their threshold or silently trim required evidence to fit Jev.

[The independent ORDER BY benchmark](https://github.com/yodablocks/jev-orderby-bench) reports passing its six predeclared gates on 360 topic-label examples, but failing four of six on 306 product-relevance examples. Its default 40-row shared-state integration failed a ranking gate that one-row requests passed. It also reports coarse probability ties and zero-call cache replay. This supports evaluating the exact domain and request shape, separating calibration from ranking, and caching unchanged judgments. It does not establish a universal one-row rule or transferable acceptance threshold. Our existing Jev screen retains one coherent pair per state and batches only related questions; we do not pack an unrelated maintenance backlog into one Jev state.

[OpenRouter's verified-cascade cookbook](https://openrouter.ai/docs/cookbook/evaluate-and-optimize/jev-verified-cascade) supplies an implemented draft/verify/escalate pattern. Its detailed 50-question results report the cascade at $0.012 with no wrong shipped answers, a frontier-only route at $0.175 with two wrong answers, and the cheap model alone at $0.004 with none wrong. The introduction inconsistently describes the frontier comparison as also having zero wrong answers. The cascade also handed off two answerable questions. We rely on the detailed account as an illustrative, limited vendor experiment, not the headline as qualification. Most importantly, its cheap-model baseline was already sufficient on those cases: adding a verifier is not automatically an improvement.

[TypeSafe's SDE cascade](https://docs.typesafe.ai/cookbooks/sde_cascade.md) provides another draft/verify/escalate implementation, with a vendor experiment over 100 extraction prompts. Its useful idea is checking specific fields against the same evidence and evaluating the complete cost/quality frontier. It does not justify applying extraction results or example thresholds to context scope, authority, or memory deletion.

## Local evidence and resulting choice

The [existing evaluation record](README.md) retains the Neri agent's useful adverse experience: broad screening retained 18 of 18 candidates, so it demonstrated no downstream savings; Jev confused absent/out-of-scope evidence with contradiction in one comparative case. A prompt correction was a repeat, not a fresh holdout. Our 13-case synthetic context screen matched its labels and replayed without calls, but neither those cases nor the outside reports measure production maintenance outcomes.

Consequently:

- Known scope, exact duplicates, source revisions, ownership and derived token counts stay deterministic.
- Existing validated reviews become actionable queue entries without another model call. Synthetic evaluations never become real maintenance work.
- The existing Memory Curator handles changed evidence in the existing scheduled batch. Items sharing a review context share a generative review request and compare against applicable neighbors. Other sessions receive only relevant handoffs, their own unfinished claims, or unreported owner decisions.
- Jev remains an explicitly selected, catalog-backed, cached pair screen. Its output can create a candidate for investigation; it cannot approve an edit, suppress uncertain work, or assert access to hidden native prompts.
- No new Jev calls are added to session startup or the scheduled maintenance default. We have not qualified a cheaper generative replacement for the current curator. The measured saving here comes from removing repeated work and unrelated input, not an unsupported model-quality claim.

A new default verifier or cheaper curator would need representative frozen cases, equal evidence, independent outcomes, and the entire workflow's quality, latency, usage-priced cost, escalations, misses and owner effort. Retain adverse outcomes. Do not infer savings from model price or agreement alone.

## Implementation measurements

`maintenance-packet-receipt.json` compares preparation of the same ten live memories: 75,438 estimated input tokens with the old whole prompt catalog, 20,745 with applicable candidates and required authority, a 72.5% reduction. No model was called. This is a request-preparation measurement, not delivered provider tokens, billed dollars, or accuracy. The discovery coverage explicitly remains non-exhaustive.

Repeat against current live state with a new output filename:

```sh
PYTHONPATH=backend backend/.venv/bin/python -m scripts.evaluate_context_maintenance --output /tmp/maintenance-packet-new.json
```

The first live deterministic sweep repaired 23 stale stored token counts, with no curator or Jev calls. `maintenance-live-receipt.json` retains two resolved redundancy items and 21 actual canonical generation checks. An actual persona preview exposed a legacy exclusion that contradicted three persona prompts requiring the global Safety Directive. One reversible canonical change removed that exclusion and archived the two now-redundant mandate memories. A subsequent managed persona preview includes the Safety Directive and omits those memory UUIDs.

The initial local multi-surface check omitted worker credential initialization: optional Gemini reference selection used its existing fallback. That limitation remains in the receipt; required-policy generation passed. No native model consumption or general optional-retrieval health is inferred from it.

`maintenance-worker-receipt.json` retains the actual scheduled-worker trial: two curator calls both proposed an invalid compact format for a required rule. Server validation rejected both complete proposals, retained their responses for agent investigation, and left every reviewed source revision unchanged. The worker loop completed; semantic review quality did not pass. Replaying unchanged work made zero model calls. The canonical schema now describes its existing cross-field constraints explicitly; we have not used another paid run to claim that wording change qualified the curator. No owner decision is required to investigate these failures.
