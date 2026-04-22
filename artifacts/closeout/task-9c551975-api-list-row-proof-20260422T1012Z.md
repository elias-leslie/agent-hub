# task-9c551975 API list-row contract proof

Updated: 2026-04-22T10:12Z
Task: task-9c551975

## Contract sources

- schema: `backend/app/api/schemas/sessions.py`
- UI contract fixture: `frontend/src/__tests__/sessions.test.tsx`
- execution artifact: `artifacts/closeout/task-9c551975-negative-proof-suite-20260422T100515Z.txt`

## Required `GET /api/sessions` core list-row fields

From `SessionListItem` in `backend/app/api/schemas/sessions.py`, the closeout-required core row contract is:
- `id`
- `project_id`
- `provider`
- `model`
- `status`
- `agent_slug`
- `session_type`
- `message_count`
- `total_input_tokens`
- `total_output_tokens`
- `created_at`
- `updated_at`

## Additive / nullable field proof

The focused `frontend/src/__tests__/sessions.test.tsx` fixture intentionally includes additive fields that can be null or absent while core fields remain intact:
- second row has `agent_slug: null`
- second row has `fallback_reason: null`
- second row omits `live_activity`
- first row includes additive requested/effective identity plus `event_count`

## Why this satisfies the closeout seam

- core fields remain present on every mocked list row used by the operator ledger tests
- additive fields vary between populated and null/omitted states in the same focused proof artifact
- the sessions UI tests then prove the operator surface keeps message count separate from event count and renders requested/effective/fallback semantics without requiring every additive field to be populated

## Direct UI proof tied to this API contract

- `surfaces requested-to-effective model identity, fallback reason, and separate message/event counts`
- `shows a no-match state that tells operators filters only apply to the loaded subset`
- `keeps row context visible and shows a local evidence error when detail fetch fails`

Together these provide a direct list-row contract artifact plus one null/absent additive-field example for closeout.
