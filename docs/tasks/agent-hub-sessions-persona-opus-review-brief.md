# Opus 4.7 design review brief

Please review Agent Hub's current `/persona` and `/sessions` surfaces as an operator UX redesign problem.

Artifacts:
- Reference contract: `docs/tasks/agent-hub-sessions-persona-operator-refactor-reference.md`
- Persona screenshot: `/home/kasadis/.hermes/cache/screenshots/browser_screenshot_b3b253cd8578454791ae2ef336ba90fd.png`
- Sessions screenshot: `/home/kasadis/.hermes/cache/screenshots/browser_screenshot_3084e237b916410788d802fb30f2c6dc.png`
- Current page entrypoints:
  - `frontend/src/app/persona/page.tsx`
  - `frontend/src/app/sessions/page.tsx`

## Current problems from code + UX audit

### `/persona`
- Too many overlapping control surfaces spread across page header, thread header, run HUD, operator deck, and composer/footer.
- Runtime truth, feed truth, preview truth, and local draft truth are mixed in ways that are structurally correct but visually under-explained.
- Some controls over-promise relative to backend semantics unless copy/scope is clarified.
- Lane count and workflow stage linkage are easy to misread.
- Transcript is readable but not strong enough as an evidence/proof surface.

### `/sessions`
- Search/filter state is client-side over paginated data, so the page can imply broader truth than it actually has.
- Expansion/detail fetches are vulnerable to stale-response races.
- Live-session affordances are weak and partially placeholder-driven.
- The row interaction model is dense but semantically brittle.
- Requested vs effective execution identity is not surfaced strongly enough.
- Empty/error states are not explicit enough about what kind of absence/failure is happening.

## Design objective

Make `/persona` the active operator cockpit and `/sessions` the forensic ledger. They should feel like adjacent parts of one serious command system, not separate dashboards.

## What I want back

Please provide:
1. A concise critique of the current visual/interaction design.
2. One cohesive design direction for both pages.
3. A concrete page hierarchy for `/persona`.
4. A concrete page hierarchy for `/sessions`.
5. A shared visual language/tokens/components recommendation.
6. Specific guidance on how to express truth/provenance without making the UI ugly or noisy.
7. The top 10 implementation priorities in the order you would tackle them.

Be opinionated and optimize for excellent operator UX, not generic SaaS admin styling.
