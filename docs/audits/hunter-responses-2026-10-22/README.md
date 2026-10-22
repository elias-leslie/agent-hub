# Neri hunter response accounting

Agent Hub's existing Activity endpoint and page now include a compact **Neri hunter responses** disclosure. It uses only sessions explicitly assigned to Neri with the hunting or recon work role. This adds passive accounting to the existing service; it changes no hunting policy, recorder, target records, or lab behavior.

The former response-token evidence still describes normalized user turns. The new, separate `hunter_responses` evidence counts unique provider responses, so many Pi responses in one user turn remain distinct. It is never added to ledger totals.

## What the numbers mean

- A valid `scope=response` usage event needs a stable response ID and nonnegative integer input/output counts. The first retained valid usage event per session/response is counted once; later duplicates are counted as excluded. Thread/cumulative counters are not added. Invalid response usage is counted as unusable, with unknown missing size.
- Inclusive reported input and output remain separate. Cache read/write are subsets of inclusive input and never add again. Cache detail coverage shows the inclusive input with a valid cache split; uncovered input has an unknown split.
- Pi tool calls join only through the adapter's exact `message:<response_id>:<block index>` identity. User-turn IDs, nearby timestamps, call IDs and guessed intent never join a response. Other harnesses' response usage is retained but currently unknown for purpose. Unlinked calls are counted explicitly.
- The four categories are investigation only, mixed, support/coordination, and unknown. Both response share and inclusive-input-plus-output token share use the same retained response set. A mixed response stays whole; no tokens are divided between its tool calls. Capped event samples make all response categories unknown.
- Investigation is a conservative invocation signal: known source read/search tools or bounded shell forms pointing at configured source extensions/directories, plus the explicit Bugout recon-run prefix. It does not establish successful execution, a bug finding, exact token intent, or an accepted outcome. Instruction/document reads, unsupported shell syntax, opaque lab commands, and other unrecognized actions remain unknown. Source-like paths can still refer to support code; the classifier cannot establish target purpose from metadata.
- Per session, the first observed investigation shows its action, linked sampled response number/input when available, and elapsed time since the first sampled provider response. Hub creation time is registration/import time, so it is not used to claim native startup delay. Response ordinals and first observations apply only to the selected window/sample; earlier work may be absent.
- First and peak input are **per response**. The cumulative input total includes repeated input across calls. Neither value proves resident context, compaction behavior or causal spend.

Classification choices live in the existing `activity_policy.json`. The output contains no prompt, tool body, command, path, search text, target content or provider-native usage body. Session/project/harness/work-role identities and numeric observations remain available for existing drill links.

## Verification

Managed quick checks passed 42 backend and 30 frontend tests, Python/TypeScript checks, Ruff/Biome and gitleaks before the final action-label correction; the scoped commit runs the managed gate again. Synthetic regressions cover Pi response linkage within one user turn, deduplication, mixed/unknown purpose, missing links, other harnesses, explicit role/project scope, source/recon invocation signals, inclusive cache partitions, cutoff/cap behavior, empty/ambiguous shell input, API-boundary validation, zero/missing values and unavailable/empty/capped UI states. The [backend-generated response fixture](../../../frontend/src/__tests__/fixtures/hunter-responses.json) is checked by both backend and frontend tests.

The actual component was rendered with that synthetic fixture and existing deployed CSS, then inspected through isolated managed Chrome. [Desktop](desktop.png) is 1280×720; [phone](mobile.png) and [phone session details](mobile-session.png) are 390×844. [Rendered text and coverage](rendered.json) retain matching observations from 2026-10-22 around 21:59–22:00 UTC. There was no horizontal overflow at either width or with 200% CSS zoom. Native Enter closed/reopened the disclosure; Tab reached the session link with visible amber focus. The link's parameters were inspected without following it into session content.

Design guidance: approved shared guide revision 3, existing Agent Hub dark tokens/components, and the retained ST Activity styling baseline. No Agent Hub copy profile is selected; copy follows the owner's plain voice. This is a bounded disclosure addition, not a redesign. Populated screenshots are synthetic evidence, not live measurements. Component tests cover additional states; no formal accessibility claim is made.

Deployment and live verification are pending the local checkpoint. No target content was inspected and no hunt or lab command was run for this work.
