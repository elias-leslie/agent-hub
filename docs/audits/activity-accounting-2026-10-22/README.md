# Activity accounting: landed and live

Implemented for task `task-5400247baf744a5f` and landed in Agent Hub main. Independent GPT-6.1 Sol xhigh review found and rechecked two fixes: PostgreSQL JSONB type handling and preference for retained full output over the 2,000-character event summary. The combined source passed managed checks and deployed on 2026-10-22.

Activity now leads with recorded usage and an admin transcript estimate. Project/session rankings and reliably linked tasks show recorded tokens and admin transcript characters. Missing session usage is labelled unavailable; project/task rows count missing-usage sessions. Existing tool occupancy, sample caps, source gaps, task-link rules, retry and stale states remain visible. The sidebar label remains **Activity**.

The conflicting **Window Cost** card is removed. Its newly-created-session/CostLog totals could not describe Activity's windowed usage. The page links to Costs for spend and pricing coverage. Other hotspot diagnostics retain their existing scope; no hotspot ingestion or billing rewrite was made.

## Calculations and coverage

- One primary usage source per Hub session, preserving existing precedence: `cost_logs`, matched `usage_calls`, then unique response events. Alternatives are not added. Source counts and recorded-token totals are shown. Partial/disjoint source histories can still omit usage; this is not a reconciled bill.
- Ledger input is `input + cache_read + cache_write`, with output separate. Cache read/write are **subsets** of the displayed inclusive input, never added again to the denominator. Native Codex response input already includes cached input; output already includes reasoning. Cache detail coverage counts inclusive input with valid retained cache detail. Missing cache detail contributes no claimed cache count and does not count as covered input.
- Global recorded tokens = inclusive input + output. Window filters apply to accounting occurrence timestamps, including old-but-active sessions. The event cap does not cap ledger sums. Response-event-only fallback can be capped. Unmatched native ledger calls now survive an outer join; unmatched completion accounting also remains in global unknown usage. Those calls are counted explicitly and excluded from project/session/task rankings because no Hub association is established.
- Ledger token purpose remains unknown. Existing response evidence describes the mix of observed tools within a normalized turn; it does not allocate causal spend. Conflicting native turns and capped event samples remain mixed/unknown. No stronger turn allocation was introduced: response identities do not prove which prior text was resident, reread, compacted or responsible for subsequent usage.
- Transcript estimate = normalized call argument characters + retained returned-text characters, once per deduplicated `(session, call_id)`. Call arguments use compact Unicode JSON, excluding Hub projection metadata; opaque custom-call `raw` text is counted directly. This is a text-size proxy, not an invented character-to-token conversion.
- Returned-text length is calculated in SQL without selecting output contents: one complete retained string (`result`, `content`, `output`, or `message` in event-storage order), otherwise combined string stdout/stderr, otherwise the event content summary. Alternate representations are not added. An empty string is known zero; absent/opaque-only output remains unknown. Nothing attempts to reconstruct truncated or unretained output.
- Exact `nested_command_digest` wrapper correlations suppress the wrapper call/result and retain native observations. Duplicate call/result observations are counted once. We do not treat `single_open_exec` as proof of identity; ambiguous wrapper matches can still duplicate text, and the UI says so.
- Admin transcript numerator combines administration and necessary support, using the existing conservative classifier. The denominator includes sampled substantive, admin and unknown/mixed tool text. Returned-text call coverage, unknown/mixed characters, wrapper exclusions and event cap are explicit. Prose, system instructions, images and protocol framing are outside this denominator. Character shares do not describe all transcript text or actual resident context.
- Project/session/task rows rank by recorded tokens, bounded by the existing API limit with shown/total counts. Tasks still require exactly one durable project/task binding. Session totals do not prove exclusive work for that task.
- A recorded nonnegative integer duration, including **0 ms**, is usable. Missing or invalid durations stay missing. Zero adds no occupancy and no missing-duration count.

## Retained sample and checks

The [backend-generated synthetic response](../../../frontend/src/__tests__/fixtures/activity-accounting-snapshot.json) covers two Hub sessions and one unmatched ledger call. It is an accounting fixture, not a production measurement. The frontend validates this exact payload and checks its displayed text and linked task session.

| Sample measure | Calculation/result |
| --- | --- |
| Inclusive input | 1,000 + 2,000 + 100 = **3,100** |
| Output | 20 + 100 + 10 = **130** |
| Recorded tokens | 3,100 + 130 = **3,230** |
| Cache read / write, already inside input | **2,350 / 200** |
| Cache detail coverage | **3,100 / 3,100 input tokens** |
| Purpose coverage | **100% unknown** ledger tokens |
| Unmatched accounting | **110 tokens / 1 call**; excluded from Hub rankings |
| Transcript arguments / returned text | **38 / 520 characters** |
| Admin text | 33 argument + 500 returned = **533 characters** |
| Sampled tool text | 533 admin + 25 substantive = **558 characters** |
| Admin proxy share | 533 / 558 = **95.5%** |
| Known duration coverage | **2 / 2 calls**, including one recorded 0 ms result |
| Ranking | `p2` / session `old`: **2,100 tokens**; `p1` / `s`: **1,020 tokens** |
| Task linkage | `task-real`: **1,020 tokens / 533 admin characters**; **2,210 tokens** unlinked globally |

The isolated SQL fixture executes the actual generated aggregate/event queries against SQLite, with a small `jsonb_typeof` test function for PostgreSQL's JSONB type predicate. PostgreSQL compilation is also checked against the migration-defined JSONB column. It verifies cache partitions, legacy Claude provider aliases, child identities, unmatched usage, empty results, opaque output, separate stdout/stderr, duplicate content/output storage, and full retained output when the content summary stops at 2,000 characters. The event query returns lengths, not content/output values. This does not claim production PostgreSQL runtime verification.

Focused managed checks: `st check --quick --changed-only` covers architecture, Ruff, Python types, 17 backend tests, Biome, TypeScript, 13 frontend tests and gitleaks. Frontend coverage includes backend-payload validation, accounting/proxy labels, ranking links, legacy-card removal, missing usage, zero values, sample caps, loading/unavailable/empty/error/stale states and retry. The final commit runs the managed quick gate again. Gate details remain in the worktree's ignored `.dev-tools` directory.

The worktree initially had no installed dependency directories. Ignored links to the existing checkout's dependency installations enabled ST checks without changing lockfiles or dependencies. Missing package-level links initially caused React resolution failures; adding those links resolved them. Interim fixture-shape/test failures were fixed before the final passing gate.

## Files and verification limits

- `backend/app/services/activity_accounting.py`: numeric normalization, argument character counts, transcript aggregation and retained usage partitions.
- `backend/app/services/admin_activity_cost.py`: bounded length query, windowed usage partitions, unmatched-call coverage, rankings and zero-duration fix.
- `backend/tests/services/test_admin_activity_cost.py`: accounting and SQL regression fixtures.
- `frontend/src/lib/api/activity-cost.ts`: types and existing runtime boundary validation for the additive accounting fields.
- `frontend/src/app/admin/components/ActivityAccounting.tsx`: primary usage/proxy display and project/session ranking drills.
- `frontend/src/app/admin/components/ActivityCostPanel.tsx`: accounting-first composition, task coverage/proxy and existing tool diagnostics.
- `frontend/src/app/admin/components/SessionHotspotsPanel.tsx`: conflicting financial card removal.
- `frontend/src/__tests__/activity-cost-fixture.ts`, `activity-cost.test.tsx`, `fixtures/activity-accounting-snapshot.json`: contract, component and cross-boundary sample evidence.
- This report.

Design guidance: approved shared product guide revision 3 at `/srv/workspaces/projects/slopminer/profiles/design-shared.json`; the live profile directory has no Agent Hub copy profile, so copy follows the owner voice. Existing dark surfaces, section cards, links and responsive grids are reused. The retained original desktop capture in `docs/audits/activity-cost-2026-10-22/admin-live-desktop.png` was inspected as a baseline; it is not evidence of this change.

**Unmet owner goal:** actual admin causal token spend and admin share of resident working context remain unavailable. This change supplies native token accounting and a prominent, bounded history-text proxy, with that limitation stated in the UI. No dollar allocation, resident-context percentage, avoidable-waste claim, telemetry rewrite or invented task association is supplied.

**Live verification (2026-10-22 16:39 UTC):** The authenticated Agent Hub Activity page rendered the new accounting from the deployed PostgreSQL service. It showed 945,979,536 recorded tokens in the rolling 24-hour window (942,738,095 input, including 925,674,230 cache-read tokens, and 3,241,441 output), 2,010,190 admin transcript characters / 38,984,830 sampled tool characters (5.2%), project and session drill links, and the existing 58.0% measured admin/support tool-time share. The event sample was capped at 20,000 and all provider tokens remained unknown/mixed for causal tool purpose. No task qualified for reliable linkage in that window; the UI showed this explicitly. The old Window Cost card was absent. The standard isolated headless browser could render the route but its API calls were denied (403) because it lacked the owner's authenticated profile; the live verification used the already authenticated Chrome tab. Component tests cover partial, stale, empty and error states, but those states were not reproduced in production. A new focused ST attribution task addresses the remaining command-level text/time gap.
