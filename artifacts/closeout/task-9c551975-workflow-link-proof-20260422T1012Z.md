# task-9c551975 workflow-link accessibility proof

Updated: 2026-04-22T10:12Z
Task: task-9c551975

## Direct proof artifact

- focused test file: `frontend/src/__tests__/persona-workflow-composer.test.tsx`
- named case: `keeps stages advisory and unlinked when the workflow response lacks a persisted session id`
- execution artifact: `artifacts/closeout/task-9c551975-negative-proof-suite-20260422T100515Z.txt`

## Failure mode covered

- stage payload uses `session_id: null`
- rendered expectation is advisory / unlinked state, not fake session linkage

## Assertions locked by the test

- stage content renders: `clarify advisory output`
- advisory scope copy renders: `Advisory output only`
- no fake linked session badge renders: `Stage session · ...` is absent
- advisory provenance remains visible on the stage card

## Contract seam satisfied

This is the direct `api-3` / workflow-link degraded-state proof for the null-session-id accessibility path:
- no concrete accessible session id
- no navigation success fabricated
- stage remains advisory and inspectable only
