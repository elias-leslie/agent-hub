# Retained-native receipt recovery

Scoped service consumers send `X-Agent-Hub-Internal` using the existing managed
internal service secret and `X-Client-Id` using their registered client ID.
These authenticate a trusted application service, not a human. Ordinary
`X-Client-Id` middleware performs identification only.

The receipt handler resolves the registered client explicitly after verifying the
service secret. Do not add the internal bypass header indiscriminately to
existing native `/complete` requests: their existing identification path supplies
the client identity used for continuation ownership.

## Receipt lookup

`GET /api/complete/native/receipt` accepts these query parameters:

- Required: `session_id`, `project_id`, `generation`, `request_id`,
  `controller_generation`.
- Optional exact-identity assertions: `expected_turn`, `context_version`,
  `payload_hash` (64 lowercase hexadecimal characters).

The verified service client must own the existing session and retain project
access. Generation and controller generation must still match. The response
contains `status` (`completed`, `uncertain`, `failed`, or `superseded`), receipt
identity/status/error metadata, and `completion` only for a completed receipt.
The completion reuses the existing `CompletionResponse` projection, including
observed usage and `native_continuation.duplicate=true`.

Missing sessions/receipts and non-owned sessions return 404. A changed generation,
controller, or asserted request identity returns 409. These responses do not
prove that an absent receipt was never dispatched. No lookup creates a session,
generation, provider turn, canonical-context request, or completion telemetry.
Successful lookup responses use `Cache-Control: no-store`. The caller remains
responsible for applying a recovered proposal only once at its own current
execution boundary.
