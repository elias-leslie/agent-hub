# Shared push and retained-native receipt recovery

New scoped consumers send `X-Agent-Hub-Internal` using the existing managed
internal service secret and `X-Client-Id` using their registered client ID.
These authenticate a trusted application service, not a human. Ordinary
`X-Client-Id` middleware performs identification only.

The new handlers resolve the registered client explicitly after verifying the
service secret. Do not add the internal bypass header indiscriminately to
existing native `/complete` requests: their existing identification path supplies
the client identity used for continuation ownership.

## Push

The existing routes remain:

- `POST /api/push/subscriptions`: browser `endpoint`, `keys`, optional
  `expirationTime`, and optional `application_id` assertion.
- `DELETE /api/push/subscriptions`: `endpoint` and optional `application_id`.
- `POST /api/push/send`: existing notification fields and optional
  `application_id`. `project_id` remains display metadata, not routing authority.
- `GET /api/push/vapid-key`: public VAPID key.

Application scope comes from the server's registered client: configured
SummitFlow first-party identities bind to `summitflow`; another client with
exactly one allowed project binds to that project (for example `neri`). Broad or
ambiguous project access does not select a push application. A supplied
`application_id` must match this binding. The owner is the registered client ID;
payloads cannot supply another owner. Subscription responses expose the binding
and ID, never endpoint keys. Sends return the count accepted by push providers;
they do not establish display or human receipt.

Endpoint uniqueness remains global because each application service worker has
its own subscription endpoint. Re-registering an endpoint cannot overwrite a
different application or owner's subscription. Existing rows keep NULL scope.
Only an explicit registration presenting the original endpoint keys may bind a
legacy row; the migration does not infer an application or owner.

The existing identified SummitFlow proxy retains an explicit compatibility
path: it can send to its own scoped subscriptions and unscoped legacy rows,
never another application. Verified scoped calls do not include legacy rows.
Direct Agent Hub transport callers default to its dashboard application owner,
not a broadcast. Neri must register its own application service-worker
subscription before receiving alerts. Application inboxes remain in their
respective applications.

The additive migration refuses to erase ownership. A code rollback must retain
the scoped send filter: old broadcast implementations are incompatible once
scoped subscriptions exist.

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
