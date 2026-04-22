# Agent Hub sessions + persona operator refactor reference

Authoritative offline design contract for the SummitFlow task package that refactors `/sessions` and `/persona` into a cohesive operator-grade control surface.

## Product intent

Agent Hub is not a consumer chat app. It is an operator cockpit for supervising autonomous work, inspecting execution truth, steering live runs, and understanding why the system did what it did.

The redesign should feel like a dark command deck: high signal density, calm visual hierarchy, strong operational clarity, and explicit separation between authoritative truth, preview/advisory data, and operator intent.

## Product guardrail alignment

This document extends `docs/persona-operator-contract.md`; it does not replace it.

Key inherited guardrails to preserve during this refactor:
- `/persona` stays primary operator surface. `/sessions` supports it as forensic ledger, not peer chat shell.
- Session truth stays grounded in `fetchSessions` / `fetchSession` plus `parent_session_id` and `live_activity`.
- Workflow stages stay advisory orchestration over current backend primitives unless backend exposes a stronger primitive.
- Prompt-budget truth stays runtime-first, preview-labeled when runtime totals are absent.
- Redirect/stop/fork semantics must not over-promise backend scope.

## Authority and tie-break order

If sources disagree, use this precedence order:
1. `docs/persona-operator-contract.md` for product/interaction guardrails.
2. This reference doc for the concrete page hierarchy, truth-source matrix, degraded states, and shared visual language.
3. Live backend/API truth for what the current system can honestly claim in the UI.
4. Claude Opus 4.7 design guidance, only where it does not contradict 1-3.

If design guidance conflicts with the backend’s actual guarantees, the UI must degrade to truthful backend semantics and record the conflict rather than faking a stronger primitive.

## Shared system rules

These rules are binding for both pages:
- One sticky command/header surface per page owns primary page actions.
- One primary evidence surface per page owns drill-down proof.
- Summary copy must not hide provenance when a source badge is required.
- Repeated actions must collapse into a single canonical control rather than appearing in multiple rails with different labels.
- Page-specific differences are allowed only when the underlying user job differs: `/persona` is active supervision, `/sessions` is historical/forensic review.

## Non-negotiable truth model

### Source badges
Every critical panel or datum that can be confused should declare its source using a compact badge or label:
- Runtime
- Session
- Preview
- Advisory
- Draft

### Sessions truth
- Active or recent session truth comes from session records.
- Parent/child lane truth comes from `parent_session_id`.
- Live execution truth comes from `live_activity` and current session status.
- Requested vs effective provider/model must be distinguishable whenever fallback happened.

### Persona truth
- Workflow stages are advisory orchestration over existing stage sessions.
- Redirect/promote/handoff are operator intents over current primitives unless backend adds stronger APIs.
- Preview budget data must never be rendered as live exact runtime truth.
- Lane count should reflect actual child-lane truth, not inflated totals.

## Field-level truth source matrix

### `/persona`
- Command-bar execution state:
  - source: `persona.execution_state`
  - values: `active | paused`
  - if a live session exists, show runtime activity separately rather than rewriting execution_state.
- Command-bar live summary:
  - primary source: `runtime.primarySession.live_activity.summary`
  - fallback source: heartbeat/manual-trigger status copy
  - badge: Runtime for primary source, Advisory for fallback copy.
- Draft thread badge:
  - source: local unsent composer/runtime draft state only
  - badge: Draft
  - must never be styled or labeled as persisted session truth.
- Lane count:
  - source: active child sessions only
  - exclude active root persona sessions from the count.
  - count a child lane as active only when `session.status == "active"` or `session.live_activity.status == "active"`.
- Workflow stage cards:
  - source: `/api/orchestration/workflow` stage result plus real `session_id`
  - each stage card must show whether it is advisory output only or linked to a real session.
  - if a stage payload omits `session_id`, points to an inaccessible session, or resolves to stale/nonexistent detail, render the stage as advisory/unlinked instead of fabricating navigation success.
  - `accessible session_id` means a non-empty stage `session_id` that is already present in the currently loaded operator session inventory or resolves via `fetchSession(session_id)` for the current operator/project scope without 403/404/null/mismatch; otherwise it remains advisory/unlinked.
- Budget/context panel:
  - runtime context/token metrics are authoritative when present on the active session
  - prompt preview metrics are fallback-only and must carry a Preview badge.

### `/sessions`
- Total count:
  - source: `SessionListResponse.total`
  - label: Total
  - meaning: total rows matching the current server-side query scope (project/status/agent/session-type filters already sent to the backend), not the whole corpus when a narrower server query is active.
- Loaded count:
  - source: number of records fetched into the client so far
  - label: Loaded
- Visible count:
  - source: rows remaining after current client-side filters over the loaded subset
  - label: Visible
  - if search/filter is not server-backed, UI must explicitly say the visible count is over the loaded subset.
  - when `Visible == 0` but `Loaded < Total`, the no-match state should preserve a load-more / keep-loading affordance rather than implying global absence.
- Row state beacon:
  - primary source for live/stalled/reapable hints: `live_activity`
  - primary source for terminal status: `status`
  - if they disagree, show explicit runtime-vs-session provenance instead of collapsing them into one ambiguous label.
- Execution identity:
  - source fields: `requested_provider`, `requested_model`, `effective_provider`, `effective_model`, `fallback_used`, `fallback_reason`
  - primary render precedence is fixed: prefer effective provider/model display when present, else requested provider/model display when present, else legacy persisted `provider`/`model`.
  - render precedence is field-level, not atomic: provider slot uses `effective_provider -> requested_provider -> provider`, and model slot uses `effective_model -> requested_model -> model`.
  - if only one effective slot is present, the UI may render a mixed effective/requested/legacy pair per slot, but it must not synthesize a fully effective identity or hide the mixed provenance.
  - when requested and effective differ, effective renders as the primary runtime identity while requested renders as secondary requested context.
  - legacy `provider`/`model` remain compatibility fallback only and must not override populated requested/effective fields.
  - if `fallback_reason` exists without one or both effective identity fields, render degraded fallback copy for the missing slot(s) rather than inventing a replacement model/provider.
- Count semantics:
  - `message_count` must mean user + assistant messages only
  - if the UI needs total event volume, expose and label `event_count` separately rather than overloading `message_count`.
  - `event_count: 0` means a true known zero only when the numeric field is present.
  - `event_count: null` or field absence means unknown, not loaded, unavailable, or not applicable and must not render as `0`.
  - `last_activity_at`, `last_heartbeat_at`, `fork_point_turn`, and `manual_outcome` follow the same rule: null/absent means unknown or unrecorded, so the UI should omit the value or use explicit unavailable copy rather than inventing empty proof.

## Action semantics contract

### `/persona`
- Heartbeat:
  - enabled only when persona is not paused and manual heartbeat is actually available.
  - starts a manual heartbeat run and may focus the resulting session if one is created.
- Stop active work:
  - current truthful scope is session-scoped cancel, not workflow-root or persona-global cancel.
  - the UI may call `cancelSessionStream(sessionId)` only for the focused persisted session, or cancel the optimistic local draft stream when no persisted session exists yet.
  - if no focused active session and no optimistic draft stream exist, disable the control.
  - keep the operator label `Stop active work`; never imply broader cancellation than the selected/focused session or local draft stream.
- Pause/resume:
  - source of truth is persona execution state.
  - success UI should not claim the save succeeded before persistence returns.
- Redirect / Promote / Handoff:
  - only valid for persisted target sessions/lane entries.
  - a persisted target means a concrete `session.id` that already exists in `fetchSessions` / `fetchSession` or the active-child-session lane set; draft-only composer state is never a valid target.
  - the active-child-session lane set is currently owned by `usePersonaRuntime.refresh()`: `fetchSessions({ status: "active", page_size: 100 })`, filtered to persona-root ids plus their non-persona children, until focused `fetchSession` detail resolves.
  - authority order is fixed: focused `fetchSession` detail wins when it resolves; otherwise the active-child-session lane set governs enablement/selection.
  - if those sources disagree or the target session id is missing, stale, or not yet persisted, disable the action and keep only inspect/select behavior until refresh resolves the conflict.
  - inactive child sessions remain valid only while their persisted `session.id` is still fetchable/inspectable.
  - must open an inspectable instruction draft before send.
  - must carry an Advisory badge or equivalent language unless/until a dedicated backend primitive exists.
  - current `/persona` lane actions remain advisory instruction drafts over existing session/message primitives even though `/api/sessions/{id}/promote` exists elsewhere; do not present persona lane promotion as an immediate backend branch mutation.
- Approve:
  - advisory-only; current continuation remains rerun or explicit next-stage execution.
- Lane count:
  - count only child sessions.
  - a child lane is active only when `session.status == "active"` or `session.live_activity.status == "active"`.
  - queued, blocked, completed, failed, or stale child entries may remain visible in the inbox but do not increment the active badge.
  - root persona sessions never count toward the lane total.

### `/sessions`
- Row expansion:
  - expand/collapse must be a dedicated control, not implicit nested-button behavior on the whole row.
  - detail fetches are latest-request-wins: if the operator collapses the row or expands a different row, stale responses must be discarded rather than painted into the newly selected row.
  - keyboard contract is explicit: row focus movement must remain predictable, Enter/Space toggles the focused row expansion, and Escape collapses the current expansion without dropping row context.
- Copy/filter actions:
  - separate explicit controls with clear focus states.
- Live evidence refresh:
  - only active/expanded sessions may poll or refresh automatically.
- List/detail data contract:
  - `GET /api/sessions` is the list truth. It must always provide `id`, `project_id`, `provider`, `model`, `status`, `agent_slug`, `session_type`, `message_count`, `total_input_tokens`, `total_output_tokens`, `created_at`, and `updated_at`.
  - list rows may additionally provide `requested_*`, `effective_*`, display-name fields, `fallback_*`, `parent_session_id`, `external_id`, `current_branch`, `summary_oneliner`, `live_activity`, and `event_count`; the UI must tolerate null/absent values without inventing stronger truth.
  - `GET /api/sessions/{id}` is the detail truth. It may extend the list payload with `messages`, `context_usage`, `agent_token_breakdown`, `working_dir`, `repo_root`, `host`, `tmux_*`, `workstream_status`, and other additive optional fields.
  - row rendering uses list data first; detail-only fields appear only after expansion fetch succeeds.

## Current audit freeze: UX deficiencies and contract gaps

This section freezes `1.1` audit findings that implementation must resolve.

### `/persona` current deficiencies
- Header and right-rail controls both act like command surfaces, so command ownership feels split instead of singular.
- `page.tsx` computes command-bar live summary from runtime or heartbeat fallback, but stop enablement is still tied to `runtime.primarySession` only; this can under-represent focused persisted child-session scope when operator is inspecting a child lane.
- `page.tsx` pause/resume path calls `updatePersona` without awaiting persistence, while header chips can still show autosave optimism; success semantics need to stay persistence-truthful.
- `usePersonaRuntime.refresh()` builds lane inventory from `fetchSessions({ status: "active", page_size: 100 })`, so active child truth is available, but inactive persisted children drop out unless later resolved through focused detail; persona lane action enablement must respect that degraded window instead of implying broad lane authority.
- Workflow preview/budget data lives beside runtime context signals, so preview fallback must stay explicitly preview-badged whenever runtime metrics are absent.
- Advisory lane actions already open inspectable drafts in `PersonaBackgroundInbox`, but surrounding command copy and action grouping still need one shared vocabulary so advisory intent does not read like immediate mutation.
- Draft thread semantics exist in `WorkspaceChatFooter`, but page hierarchy still mixes draft, persisted session, and runtime cues across multiple panels.

### `/sessions` current deficiencies
- `useSessionsData` fetches paginated rows from backend, but `useSessionFilters` applies search/model/benchmark filtering client-side over loaded rows only.
- `SessionsHeader` already warns that filter scope is loaded subset, but page empty/no-match handling still treats `visibleCount === 0` as generic no-match without preserving a stronger keep-loading affordance when `loaded < total`.
- `useSessionExpansion` already uses latest-request-wins via `requestSequenceRef`, but failed detail fetch clears data without preserving row-local error evidence; forensic context stays weak after expansion failure.
- Session row/detail rendering uses both `message_count` and `event_count`, but operator semantics must stay frozen as message-only vs separately labeled event volume.
- Live row emphasis currently mixes persisted `status` and `live_activity` hints; provenance needs to become explicit whenever they disagree rather than collapsing into a single implied state.
- Execution identity fields exist in API types and schemas, but frontend hierarchy still underuses requested-vs-effective provenance and fallback semantics.

### Backend/API audit freeze
- `GET /api/sessions` already returns additive list truth with `message_count`, `event_count`, requested/effective identity fields, lineage fields, and `live_activity`; additive shaping should stay preferred over schema churn.
- `GET /api/sessions/{id}` already returns detail payload with messages, context, token breakdown, and additive environment metadata.
- Session schemas already separate `message_count` from optional `event_count`; implementation must preserve that meaning rather than reinterpreting existing fields.
- Persona schemas expose execution state and automation metadata but do not themselves encode stronger redirect/promote/handoff primitives; persona UI must therefore stay advisory unless backend work adds narrow truthful support.
- Default scope for backend work remains additive shaping or truth-preserving service fixes. No migration is justified by `1.1` audit yet because required core data already appears derivable from existing storage/contracts.

## Degraded-state contract

### `/persona`
- No runtime session: show idle cockpit, not an error state.
- Draft exists but no persisted session: show Draft source badge and disable lane-only actions.
- Preview budget only: show Preview badge and explanatory copy.
- Backend/runtime error: show the error surface without collapsing it into empty state.
- No automation/history data: show empty-but-healthy state, not failure.

### `/sessions`
- Loading first page: dedicated loading skeleton/state.
- Backend fetch error: retryable error state with visible error copy.
- No sessions returned from server: empty-data state.
- No visible rows after client-side filtering of loaded subset: no-match state that says filters/search apply to loaded rows unless server-backed.
- Expanded detail fetch fails: keep row context and show a local evidence-panel error rather than replacing the whole page.
- Live session with missing live_activity: degrade to persisted status and omit fake live badges.

## Verification setup contract

Before any `2.x` implementation work starts, `1.1` must freeze and log one reproducible setup path for each required degraded/browser proof. Accepted setup sources are: naturally occurring runtime/browser state, focused frontend/backend fixtures, or named seed/setup artifacts recorded in the task log.

Minimum required setup map:
- preview-only budget: reproduce an idle/no-runtime persona state where preview budget data exists without runtime metrics, using either the natural idle workspace or a focused mocked fixture; the task log must name which source is authoritative.
- workflow-stage missing session link: reproduce a stage payload whose `session_id` is null/omitted/inaccessible and prove the UI stays advisory/unlinked; the setup artifact must show whether the failure mode is null, 403/404, or fetch mismatch.
- stale sessions expansion race: reproduce out-of-order detail/evidence responses with a focused test or mocked harness; browser proof may supplement it, but the race trigger must be named in a fixture/test artifact.
- persisted-child advisory draft: reproduce a real persisted child session id from the active-child-session lane inventory, then open redirect/promote/handoff draft state before send to prove the UI distinguishes inspectable operator intent from backend mutation.
- sessions no-match over partial load: reproduce a loaded subset where `Visible == 0` while `Loaded < Total`, and capture the load-more explanation rather than a false global-empty state.

## Shared surface vocabulary

Use the same visual vocabulary on both pages.

### State colors
- Live / working: emerald-teal signal
- Waiting / queued: amber-gold pulse
- Blocked / failed: rose-red
- Idle / archived / inactive: slate-muted
- Advisory / preview: violet-blue or steel accent, visually secondary to runtime truth

### Surface tiers
1. Command rail / page header
2. Primary work surface
3. Secondary intelligence rail
4. Evidence drawer / expanded detail

### Reusable modules
- status beacon cluster
- provenance/source badge row
- compact key-metric strip
- action group with explicit scope labels
- evidence panel with raw/derived toggle
- timeline rows with stronger type/status distinction

## `/persona` target layout

### Primary structure
1. Sticky operator command bar
   - persona name
   - execution state beacon
   - current live summary
   - scoped actions: heartbeat, stop active work, pause/resume, settings
   - action labels must match actual backend scope

2. Main thread/workspace column
   - thread header with current thread identity and live linkage
   - transcript/timeline area
   - composer/footer

3. Right intelligence rail
   - run HUD
   - blockers and truth source labels
   - budget/context panel
   - workflow stages with explicit stage-session linkage
   - lane inbox
   - automation state

### Persona-specific requirements
- Draft threads must visually read as draft, not persisted thread truth.
- Lane actions should open inspectable instruction drafts before sending.
- Workflow stages must expose stage lineage/session linkage and stale downstream state.
- Transcript should support a “raw evidence” mode in addition to cleaned operator summary mode.

## `/sessions` target layout

### Primary structure
1. Sticky command header
   - total sessions and visible subset summary
   - filters/search/sort chips
   - refresh state and live polling state if enabled

2. Sessions board
   - rows/cards optimized for operator scan speed
   - requested vs effective model/provider identity
   - live beacon and provenance labels
   - key metrics
   - dedicated expand affordance

3. Expanded evidence drawer
   - session summary
   - runtime vs persisted state proof
   - messages timeline
   - event timeline
   - lineage/fork metadata
   - environment/workstream metadata

### Sessions-specific requirements
- Rows should read like ledger entries, not generic table rows.
- The main list must preserve fast keyboard scan and explicit focus.
- Expansion content should separate derived summary from raw evidence.
- Visible/Loaded/Total semantics must remain visible whenever filtering is client-side.

## API / persistence scope decisions

- Prefer additive shaping on existing session/persona/workflow endpoints.
- Prefer service/query fixes over new persistence.
- DB migration is not approved by default.
- Introduce a migration only if implementation proves one required truthful datum cannot be derived safely from existing storage.
- Any new field added for this refactor must remain optional or null-tolerant for older rows.

## Task log

### 1.1 freeze record
- Latest imported plan: `docs/tasks/agent-hub-sessions-persona-operator-refactor.plan.json`
- Repo-local implementation reference: `docs/tasks/agent-hub-sessions-persona-operator-refactor-reference.md`
- Authoritative package for implementation: latest imported plan + this reference doc, interpreted under `docs/persona-operator-contract.md` authority order.
- Stale critique summaries, ad hoc notes, and pre-freeze observations do not outrank these documents.

### 1.1 setup map freeze
- Preview-only budget proof source: natural idle `/persona` workspace or focused fixture; whichever implementation/test uses first must be logged as authoritative artifact.
- Workflow-stage missing session-link proof source: focused workflow payload fixture or API/browser capture showing null/omitted/inaccessible `session_id`.
- Stale expansion-race proof source: focused hook/component test with out-of-order detail/event responses.
- Persisted-child advisory-draft proof source: active-child session inventory from `usePersonaRuntime.refresh()` plus draft-open UI proof before send.
- Sessions no-match over partial-load proof source: paginated subset test/fixture where `Visible == 0` and `Loaded < Total`.

## Open implementation constraints carried forward from 1.1

- No backend/API guessing. Any stronger cancellation, promotion, or workflow mutation claim needs explicit backend proof first.
- No count relabeling tricks. `message_count` stays message-only even if current UI wants fuller activity volume.
- No fake effective model/provider identity when only partial fallback data exists.
- No persona lane authority over draft-only state.
- No migration unless a later phase logs one missing truthful datum absent from current storage/contracts.
