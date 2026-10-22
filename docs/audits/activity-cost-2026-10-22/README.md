# Work and admin activity: delivery and evidence

Task: task-bd691794dadc475b. Observed 2026-10-22. Runtime source: `c0d01a1a01c4255c880948d2396e0a0b3eeb7b0d`. No publication.

The owner can now find repeated admin/support families across Hub projects, identify their recorded projects, and open an observed session to decide whether repetition was necessary. This supports investigating and reducing ceremony; it does not establish avoidable waste or measure all work. Necessary checks, commits and builds remain explicitly included in admin/support rather than labelled unnecessary.

Before this change, `/admin` displayed existing session diagnostics but ignored `activity_cost`. The sidebar omitted Admin; Costs and Sessions offered no activity link. The existing activity API already supplied measured category shares and gaps, but repeated families lacked project/session evidence and linked task rows lacked a session drill path. Those were the only backend aggregation additions, alongside sample/cap counts. No telemetry, new endpoint, token allocation, inferred task association or design replacement was added.

## Live measurements

The retained [actual API response](activity-live.json) covers 2026-10-21 15:19:19.595576 UTC through 2026-10-22 15:19:19.595576 UTC. It returned HTTP 200 through the authenticated production dashboard at `https://agent.summitflow.dev/api/admin/session-hotspots?hours=24&limit=5`.

| Category | Measured seconds | Share of 4,673.687 seconds |
| --- | ---: | ---: |
| Substantive | 0 | 0.0% |
| Admin including support | 2,047.932 | 43.8% |
| Unknown including mixed | 2,625.755 | 56.2% |

These are per-session unions of reported tool intervals, added across sessions. They are not elapsed time, thinking time, spend, tokens or all active work. Zero classified substantive time does **not** establish that no substantive work occurred.

Coverage: 122 sessions, 20,000 sampled events at the 20,000-event cap; 3,591 of 6,586 observed calls lacked usable duration. Mixed time was 558.924 seconds. Explicit wait-only occupancy was zero; other waiting remains unmeasured. All 122 sessions lacked a single reliable task binding; all 4,673.687 measured seconds and 862,118,425 recorded tokens remained unlinked. Twenty-eight sessions lacked usage. Recorded tokens use one source per session and are not a reconciled billing total.

The UI shows 5 of 14 repeated families, with project counts and explicit visible row limits:

| Family | Calls | Sessions | Measured seconds |
| --- | ---: | ---: | ---: |
| st.check | 140 | 23 | 911.917 |
| st.service | 74 | 10 | 650.914 |
| st.commit | 24 | 12 | 179.457 |
| compound | 110 | 17 | 147.586 |
| st.sessions | 636 | 24 | 139.233 |

Family times can overlap and must not be added. `st.sessions` is a concrete repeated coordination family to inspect, not evidence that its calls were unnecessary. No Neri session/target drill was opened. Other project names appeared only as part of the global aggregate.

## Rendered evidence and interaction

Shared design guide: `/srv/workspaces/projects/slopminer/profiles/design-shared.json`, approved revision 3. Product foundations remain the current dark tokens, section cards, buttons, links, typography and layouts. No Agent Hub copy profile was present in the live profile set or selected in project configuration; copy follows the owner's plain voice. Reviewed rendered copy for measurement meaning, qualifications, labels, reading load and useful next actions.

Baseline: [desktop image](admin-before-desktop.png), [paired text](admin-before-desktop.txt); [phone image](admin-before-mobile.png), [paired text](admin-before-mobile.txt). Signed-in Costs and Sessions were also inspected before implementation: Costs already showed spend/accounting and filters; Sessions showed history, native kinds, project filters and inline logs. Original UI source revision is not proven by the screenshot; it was captured from the pre-reload page before observing the new release.

| State/path | Evidence | Observation |
| --- | --- | --- |
| Live desktop, 1600×900 CSS pixels | [image](admin-live-desktop.png), [text](admin-live-desktop.txt) | Three measured shares, denominators, coverage, family list and no-linked-task state visible. Low-glare treatment and existing foundations preserved. |
| Live narrow desktop, 1180×900 | [image](admin-live-narrow.png), [text](admin-live-narrow.txt) | Cards remain readable; families/tasks stack into one column; no page-width overflow. |
| Live phone, 390×844 | [image](admin-live-mobile.png), [text](admin-live-mobile.txt), [capture metadata](phone-capture-metadata.json) | Shares stack, links wrap; DOM checks found no overflow in the panel or its links, and document scroll width was 390. Raw compositor image retains blank margins because CSS and compositor bounds differ in this Chrome session. Earlier cropped/timeout captures were discarded. |
| Phone navigation | [image](admin-mobile-menu.png) | Admin is labelled “Work & admin activity” in the scrollable menu, with active state. |
| Loading on live navigation | [image](admin-loading-mobile.png), [text](admin-loading-mobile.txt) | “Loading activity…” appears without invented metrics. |
| Failed initial request | [image](admin-initial-error.png), [text](admin-initial-error.txt) | Browser-only blocking of this GET produced an inline error and Retry activity, without a permanent loading skeleton. |
| Failed refresh with prior data | [image](admin-stale-error.png), [text](admin-stale-error.txt) | Last snapshot remains visible and is explicitly labelled as retained after failure. Clearing the block and clicking Retry restored real data. |
| Empty response fixture | [image](admin-empty-fixture.png), [text](admin-empty-fixture.txt) | A browser-only response replacement exercised zero denominator, absent shares, zero observed families and no linked tasks. This is synthetic state evidence, not a live empty-window claim. |
| Costs discovery | [image](costs-after.png), [text](costs-after.txt) | Explicit activity link near the summary; Enter opens `/admin#activity`. |
| Project drill | [proof](project-drill-proof.json) | All agent-hub sessions opens with native project filter value `agent-hub`, all kinds, subagents and benchmarks included. |
| Family/session drill | [proof](session-drill-proof.json) | The source-backed Agent Hub `st.check` session opened by exact ID and showed its inline session search. Sessions' activity link returned to Admin using Enter. |

The rolling live window changed between captures, so phone/narrow values differ from the frozen desktop/API snapshot. No claim of identical denominators across those capture times is made. Unavailable server data and a populated linked-task row are covered by component/API tests; no reliably linked live task existed to validate a live task row. No production binding was invented to create one.

Keyboard: Enter worked on both Costs/Sessions discovery links. Tab from the refresh control focused Browse sessions with a visible native outline. Phone/menu interaction, project selection, selected session display, retry recovery and response states were exercised. This is a bounded usability check, not a WCAG conformance claim. Temporary request blocking, response interception and viewport overrides were cleared; the review tab was left on real Admin data at normal sizing.

Fresh isolated managed browser profiles returned 401/403 because they lacked owner sign-in; those captures were not used as proof of an application access failure. CUA used a new review tab in the existing authenticated Chrome profile after the coordinator identified it. No credentials were read, copied or changed.

## Checks and deployment

Focused managed checks passed:

- `st check vitest -- src/__tests__/activity-cost.test.tsx src/__tests__/activity-cost-api.test.ts src/__tests__/admin-page.test.tsx src/__tests__/sidebar-nav.test.tsx src/__tests__/costs-page.test.tsx src/__tests__/sessions.test.tsx`: 35 passed.
- `st check pytest -- tests/services/test_admin_activity_cost.py tests/api/test_admin_api.py`: 20 passed.
- `st check tsc`: passed.
- `st check --fix --changed-only`: Ruff and Biome passed; scoped formatting applied before commit.
- The scoped `st commit` passed its managed quick gate.
- Full managed acceptance before deployment: 4,490 Python tests passed, 3 skipped; 267 frontend tests passed; types/lint/security stages passed. Biome retained an existing warning in Sessions LoadingState outside the changed files.

Acceptance receipt: `.git/st/acceptance/e314c7282355f493edcbc7935e2d01c4578a289bc69700766c42e9651401ca7e.json`.

Managed full rebuild job `00271f6179fa436797ddc021c0d42190` succeeded, including build, migrations, services, seed sync and health. Deployment receipt: `/home/kasadis/.summitflow/services/jobs/00271f6179fa436797ddc021c0d42190.deployment.json`. Backend, frontend, both Hatchet workers and the declared collection/close/sync timers were subsequently active. Browser console reported no errors after test overrides were cleared. Release source remained `c0d01a1a01c4255c880948d2396e0a0b3eeb7b0d`; this later evidence-only checkpoint needs no runtime rebuild.

## Exact implementation and test files

- `backend/app/services/admin_activity_cost.py`: observed project/session provenance for repeated families, sample session for bound tasks, family totals and tool-call coverage count.
- `backend/tests/services/test_admin_activity_cost.py`: provenance, bounded project rows, counts and reliable task drill regression.
- `frontend/src/lib/api/activity-cost.ts`: activity types, runtime validation and existing Sessions URL contract.
- `frontend/src/lib/api/admin.ts`: existing hotspot response consumes validated optional activity.
- `frontend/src/app/admin/components/ActivityCostPanel.tsx`: measured display, coverage, caps, repeated families, task/session links and state copy.
- `frontend/src/app/admin/page.tsx`: independent request outcomes, retry/stale/error handling, panel placement and honest refresh status.
- `frontend/src/components/layout/sidebar-nav.tsx`: discoverable Admin link.
- `frontend/src/app/costs/page.tsx`: activity discovery link.
- `frontend/src/app/sessions/page.tsx`: activity discovery link.
- `frontend/src/__tests__/activity-cost-fixture.ts`: synthetic contract fixture.
- `frontend/src/__tests__/activity-cost.test.tsx`: metric denominators, caps, links, loading/unavailable/empty/error/stale states and invalid input.
- `frontend/src/__tests__/activity-cost-api.test.ts`: existing endpoint, runtime boundary and HTTP failure handling.
- `frontend/src/__tests__/admin-page.test.tsx`: partial request failure, retry and retained-data behavior.
- `frontend/src/__tests__/sidebar-nav.test.tsx`: Admin navigation and active route coverage.

All additional task files are retained evidence under this directory. Unrelated source work was preserved. No agents were delegated and no publication occurred.

## Remaining attribution gaps

Unknown duration has unknown size. Unsupported/wrapped tools and mixed intervals remain unknown; substantive time can therefore appear as zero. The event cap omits older events and can break associations. Family times overlap; repeated calls are not an avoidability judgment. Project identity comes from the session, not per-command cwd or argument inference. Task association requires one durable matching project/task session binding; there were no qualifying live task rows. Native usage/accounting histories are alternatives with incomplete coverage, not exact per-command costs or billing reconciliation. Thinking, idle time and unrecorded work remain unmeasured. Those are data limits, not unresolved UI work.

Remaining: None within the agreed scope.
