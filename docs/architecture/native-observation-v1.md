# Native observation ledger v1

Agent Hub owns normalization, native command identity, source receipts and committed
positions. The v1 seam is additive and opt in: unchanged sessions continue through
the existing transcript endpoints, source IDs, byte checkpoints and query events.
Managed App Server sources start in shadow mode. The trusted local owner can
activate the implemented live command writer only after server acceptance. Rollout
ingestion remains available for recovery and exact historical ordering.

The internal execution-owner API registers a source at
`POST /api/session-ingestion/sessions/{thread}/native-sources` and ingests its
observations at `POST .../native-sources/{source}/observations`. External project
access alone does not permit registration or attestation. Sync and async client
methods and public models are in `agent_hub.models.native_observation`.

A source registration binds the existing session/project to a Codex namespace
(host plus storage identity supplied by its trusted execution owner), source kind,
producer, epoch, collector, provider version and schema fingerprint. Source IDs
include the own native thread. A registered namespace cannot be changed. The local
rollout path must match the already registered and locally verified native source;
its authenticity is `local_verified`. Forwarded App Server receipts are
`collector_attested`, not independently reread evidence. Source generation zero preserves deployed source IDs. Successors name the exact
predecessor and increment its generation while retaining namespace, thread, kind,
producer and epoch. A version or fingerprint change uses a new generation. Each
generation has its own contiguous receipt sequence; prior acknowledgements never
advance the successor. Local parser resets and rewritten byte layouts advance a
separate authority-owned `parser_generation` with an exact internal predecessor
within the existing ingestion transaction. Protocol upgrades cannot collide with
local parser generations. Original
receipts and query event IDs remain available across rewrite and backfill.

Each source has its own contiguous observation sequence, starting at one. RPC IDs,
list cursors, timestamps and transcript byte offsets are not these acknowledgments.
App Server producers must durably preserve the same epoch and sequence on retry.
Rollout command observations carry a sequence in the existing parser checkpoint,
with a registration-time baseline and exact line, byte offsets and record digest.
Only command observations count in that source sequence. Existing full-file health
and byte checkpoints retain authority for malformed records, unsupported records,
partial tails, compaction and rewrite coverage; the command ledger is not a second
full-transcript completeness claim.

Receipts retain their original observation payload and hash. Replay is idempotent;
a different payload at the same source position creates a durable conflict issue
and cannot overwrite the original. Later lifecycle observations use new positions.
Out-of-order receipts remain stored without advancing past a missing position.
Caller acknowledgment values cannot move or rewind the server position. Trusted
receipts, issues, command links and checkpoint updates use the existing session
advisory lock and one transaction. Binding failures roll back the batch and never
acknowledge unauthorized evidence.

Canonical command identity is the tuple of provider, verified namespace, own
thread, native turn and durable execution item ID. Lifecycle phases are observations
of that identity. Provisional, source-local and missing identities remain unresolved.
Active-resume command snapshots remain provisional even if a producer claims durable
IDs. No content, position, ID spelling, wrapper call ID or user correlation can
establish a command join. Unresolved snapshots create no competing query work.
Inherited observations remain tagged receipts and cannot create child command
entities. A child that shares a parent's runtime alias keeps its own thread and
separate parent relationship. Omitted lineage fields do not overwrite session
lineage. Existing fork history exclusion remains the rollout parser's responsibility.

Matching durable final command observations link to one entity and the existing
rollout tool-use/result pair. Later observations cannot rewind terminal state or
append a second pair. Contradictory canonical command/cwd/exit or terminal state
creates an issue. Changed terminal stdout/stderr/aggregatedOutput within the same
live source creates a conflict and preserves the first canonical output. Different
stream representations remain separate evidence without invented equivalence. Wrapper call IDs remain
explicit source aliases/correlations. Requested and configured model values remain
separate receipt fields. This slice has no verified provider delivery receipt, so
its entity `observed_model` is null. Legacy `native_session_id` is read only as a
transcript runtime alias; new model-evidence fields name `native_thread_id` and
`transcript_runtime_session_id` separately.

Real PostgreSQL tests create an isolated migration-owned schema in `agent_hub_test`
and exercise two-source reconciliation, provisional read/resume/read observations,
child aliases, inherited receipts, unknown delivery, unsupported payload retention,
retry conflicts, stale acknowledgments, missing prefixes, lifecycle replay,
transaction rollback and concurrent duplicate receipts. No live provider is called.

## Managed transport and retained evidence

SummitFlow now provides an explicitly launched, default-off stdio supervisor through
`st sessions managed-codex`. It starts its own App Server process; a second process
cannot observe another client's live connection. External sessions remain rollout-only.
The installed profile is `codex-cli 0.159.3`; historical `codex-cli 0.159.2`
remains supported for replay. Both use stdio JSON-RPC, with combined generated
ServerNotification/ServerRequest schema SHA-256
`6f7a929fad56ae9fc103a8364f0a7f51bd520c007b826d8e3edf5fe167c253e2`.
The 0.159.3 schemas were generated from the installed binary and match the retained
0.159.2 fingerprint. Profiles remain keyed by exact version and fingerprint; unknown
profiles cannot enter canonical normalization. Both owner and authority validate the
profile. A future exact version with an identical bundled schema can qualify only after a
complete isolated canary receipt is accepted by Agent Hub's owner-only
`POST /api/session-ingestion/native-protocol-profiles`. `GET` at the same path lists
approved profiles. Public clients expose `register_native_protocol_profile()` and
`list_native_protocol_profiles()`. Qualification requires the exact candidate
version/fingerprint, absent external network, a scripted loopback provider, positive
provider request count and all fifteen cases below. Changed schemas remain
unsupported until reviewed bundled assets exist. A qualified version cannot be
rebound to another fingerprint. Fresh successful canaries for the same version and
fingerprint acknowledge the original immutable receipt. The registry neither
installs binaries nor activates projection. SDK `schemas(version)`, `fingerprint(version)` and
`profile(version)` expose public conformance assets without normalization logic.

SummitFlow commits the original wire event to a private FULL-synchronous SQLite
outbox before forwarding it to the controlling client. Its producer, epoch, owned
thread registry and per-thread positions survive restart. A lifetime owner lease and
separate delivery lease fence competing local processes. Configuration sets an
explicit payload/catalog quota and acknowledged raw-retention duration; pending and
unbound evidence is never evicted to make room. Quota exhaustion stops capture,
records a gap where storage allows, and preserves the native connection. SQLite
page/index/journal overhead is additional to the logical payload/catalog quota.
Expired acknowledged local rows are securely deleted on capture, delivery or status;
canonical receipts and issues remain in Agent Hub. The supervisor does not decide,
decline, retry or replay approvals. Raw evidence can contain sensitive session data;
logs and status expose only counts, identifiers and fixed health classifications.

The envelope remains `native-observation.v1`: registration binds provider,
namespace, source kind, producer, epoch, collector, version, fingerprint and own
thread; each batch contains observations and an optional nonauthoritative caller
acknowledgement. Each observation contains source position, own thread, origin,
kind, original payload, source reference and optional explicit native identities,
aliases and configuration evidence. `app_server_event` stores the untouched wire
notification or request. Agent Hub derives command/lifecycle/approval/usage views;
the collector never normalizes these into canonical events. Direct collector
command/user claims in an App Server stream remain unsupported durable evidence
and cannot drive projection; validated original wire is required. Locally verified
rollout records retain their existing authority. `approval_response`
stores a response supplied by the existing controlling client. A per-connection
UUID prevents reused RPC request IDs from joining approval evidence across restarts.

Agent Hub acknowledgements return schema version, source ID, authenticity,
contiguous committed position and an exact disposition for each submitted position.
SummitFlow clears a pending receipt only after a recognized non-conflict durable
disposition names that position and the committed position covers it without
rewinding its last accepted acknowledgement. Lost responses replay the same envelope;
registration alone cannot clear pending evidence. Conflicts retain the original
local payload and block delivery of later positions for that source. Receipt replay,
unsupported shapes, unresolved identity and inherited history remain explicit.
The local acknowledged value is a delivery copy, never a canonical cursor.

Managed rollout registration sets `reconcile_existing_rollout=true` so Agent Hub
can reread and associate history even after delayed registration. It uses existing
rollout parsing and verification, does not change the byte checkpoint and does not
replay timeline events. The default false preserves deployed baseline semantics.
Exactly matched durable App Server and rollout identities share one command entity
and one canonical projection pair. Native argv versus shell display text and local
file-URI cwd representations are normalized only inside Agent Hub. Equivalent
rollout native and tool wrappers do not append duplicate command pairs.

Approvals resolve against an earlier validated request from the same source,
connection, exact JSON-typed request ID and managed thread. Responses additionally
bind the original turn/item. `serverRequest/resolved` proves the request was cleared;
it does not prove approval. Normalized receipt views persist validated turn/thread lifecycle status and
approval binding separately from the untouched envelope. Client responses are
`client_responded`; clearance is `request_cleared` and cannot imply acceptance.
Usage notifications remain cumulative snapshots with explicit nonbilling accounting
and do not add a second token delta or billing source. Requested/configured model receipts
retain their evidence category; none proves delivered model. `observed_model` stays
null. Read/resume/fork responses remain snapshots, with no inherited command replay.
Native child ownership comes from verified spawn evidence. SummitFlow subscribes
only after proving ownership; any missing prefix or failed subscription remains
an explicit health gap.

`GET /api/session-ingestion/sessions/{thread}/native-capture` exposes content-free
DB health under existing project authorization, without contacting App Server.
Internal execution-owner queries at `.../native-sources/{source}/observations` and
`.../issues` retrieve original receipts, conflicts and derived approval subjects
with bounded pagination and project/source authorization. All downstream queries,
rollout ingestion, backfill and checkpoints continue without App Server availability.

## Unbound evidence and operator summaries

`POST /api/session-ingestion/native-quarantine` registers a project/namespace/
producer/epoch/generation stream with no session foreign key. The internal execution
owner sends `NativeQuarantineBatch` to `.../native-quarantine/{source}/observations`.
Each receipt retains the original payload, nullable native subject and connection
reference. Missing positions, replay and conflicts use the same server-owned exact
acknowledgement contract. Conflicts preserve both the original receipt and new issue
evidence. No quarantine receipt creates a session, command, model delivery claim or
approval subject. Raw receipts and issues remain bounded internal evidence-owner
queries and use their immutable source project authorization.

Project-authorized `GET .../native-quarantine?project_id=...` exposes counts and
last receipt time without raw evidence. Session capture health adds supported
provider profiles, exact compatibility, generation, disposition counts and receipt
freshness (`never_observed`, `recent`, `stale` after five minutes). Receipt freshness
is server arrival time, not a runtime heartbeat or completeness proof. Delivery
status is explicitly collector-reported only. Promotion eligibility and its current
blockers are server-owned; source registration contains no activation switch.

`GET .../sessions/{thread}/native-evidence-summary` provides canonical entity IDs,
projection event IDs and safe receipt provenance (source ID, position, source kind,
authenticity, origin and disposition). Approval summaries count validated requests,
bound responses, clearance and unresolved bindings without response decisions or
raw content. Inherited and unresolved evidence remain explicit counts. These queries
read Agent Hub's database and have no App Server availability dependency.

## Explicit user aliases

User-message aliases use a separate provider correlation, not command identity.
The installed 0.159.3 isolated proof preserved request `clientUserMessageId` as
response `userMessage.clientId`: active read's durable UUID, active resume's
provisional `item-1`, and final read's original UUID shared the exact client ID,
own thread and native turn. Agent Hub validates the own-thread snapshot shape and
derives the join; collector alias claims cannot establish it. Identity is scoped
by namespace, own thread, native turn and client ID. Conflicting durable IDs create
a visible issue without overwriting the original. Parent/sibling identities cannot
join. Copied fork history stays inherited; a matching validated live user in the
owned fork can prove a new owned turn.

Snapshots establish aliases without replaying user timeline history. Distinct
alias identities retain first positions; the receipt ledger preserves all source
positions. The permanent sanitized fixture contains correlation metadata and
native identifiers without user text. This proof does not establish command joins
where active/final reads omitted the interrupted command.

## Live projection and owner control

Server-owned `NativeProjectionState` defaults to `shadow`. Eligibility requires
server acceptance, a qualified `summitflow/codex-managed` source and verified
rollout recovery. Activation revalidates native provenance. Registration cannot
activate projection and there is no collector-facing promotion endpoint.

In `canonical_managed`, a validated running command creates only `tool_use`.
Terminal completion adds `tool_result`; started observations never manufacture a
result. The writer reserves collision-checked provisional positions and exposes
`native_turn_id` and `ordering: provisional` in event tool input. Exact rollout
identities atomically relocate the same UUIDs to legacy turn/sequence/source-event
positions and adopt rollout presentation. A partial pair receives its missing
result without duplicating the use event. Concurrent live/rollout/replay paths share
the existing lock and accounting.

Safe audit rows use `native_lifecycle` and `native_approval`, with native turn,
method, kind and provisional ordering, without raw approval contents or inferred
decisions. Approval audit identity includes the exact JSON-typed validated RPC ID,
connection and bound request position; distinct requests for one item do not
collapse. Requested/configured model evidence remains separate, and usage snapshots
add no second accounting delta.

The trusted Agent Hub ST extension operates the local authority:

```sh
st native-sessions status THREAD
st native-sessions acceptance THREAD --canary-receipt FILE --identity-receipt FILE --gate-receipt FILE
st native-sessions projection THREAD --mode canonical_managed
st native-sessions projection THREAD --mode shadow
```

Acceptance reads bounded owner-owned files and invokes the canonical public
`st --no-compact check --acceptance --sha HEAD --json` from Agent Hub's fixed root. It compares
the current acceptance ID and source commit/tree, verifies isolated runtime and
identity receipts, binds the session's managed/verified rollout sources, and checks
reconciled terminal pairs and retained user aliases. It records acceptance without
activating the writer. The explicit projection command activates only eligible
state. `shadow` immediately returns authority to rollout without deleting evidence.
Driver failures produce content-free errors. These commands use the owner's
backend environment, without a collector secret or ad hoc SQL. Deployment promotion
remains a separate operator action after the full gate.

The accepted runtime backend remains the module authority for status, projection
and retention. Git acceptance alone runs from the fixed registered host checkout,
because the deployed archive has no Git metadata. Its bounded owner-owned managed
release receipt must bind that exact backend source root, and its accepted
commit/tree must match the canonical ST gate. Missing, invalid or stale source
bindings reject acceptance; the owner must rebuild before using a newer checkout's
gate. This read-only guard does not replace ST's release or acceptance authority.

## Raw retention

Original wire evidence can contain prompts and approval contents. Agent Hub has no
guessed raw TTL. Its trusted owner supplies an explicit cutoff:

```sh
st native-sessions prune-raw --project PROJECT --older-than 2026-10-01T00:00:00Z --limit 100
st native-sessions prune-raw --project PROJECT --older-than 2026-10-01T00:00:00Z --limit 100 --apply
```

The first command previews. Apply prunes only committed, clean,
retained/accounted/reconciled receipts with preserved normalization. Pending,
unresolved, unsupported, quarantined and conflicted evidence stays protected.
Pruning removes original payload content while retaining its immutable hash,
source position/references, subject, normalized approval audit, ledger and event
provenance. Exact typed approval request/connection/turn/item/position survives,
allowing late resolutions and replays after pruning without losing audit counts.
Conflict issues are preserved. The migration refuses a destructive downgrade while
quarantine sources exist; runtime rollback uses `shadow`, not schema removal.

Browser clients use the sanitized project-authorized health and evidence summaries,
never internal raw APIs. Command summary pagination uses `after_entity_id` and
`limit` (default 100, maximum 1000); provenance is bounded at 10000 rows with a
truncation flag. User alias summaries are bounded. Status is database-backed and
has no App Server availability dependency.

## Verification and remaining deployment evidence

On 2026-10-01 the focused ST PostgreSQL/API/SDK/owner-CLI gate passed **43 tests,
zero skipped**, using the real isolated 0.159.3 fifteen-case canary export. The
canary used a network namespace, no credentials and a scripted loopback provider.
All required cases passed: completed command, live approval request/resolution,
interruption/resume, compaction, fork snapshot, native child, owned child
subscription, supervisor restart/resume, usage snapshots, rollback to rollout,
safe reenable, process-owner fencing, external-thread rejection, quota preserving
native execution and exact client-message identity.

The PostgreSQL fixture creates a unique migration-owned schema in the existing
test database; tests call no external provider. Coverage includes registration
before/after rollout ingestion; historical-profile replay; protocol/parser
generation isolation; same-inode rewrite; quarantine ACKs/conflicts; live-first
partial/terminal projection and exact relocation; concurrent live/rollout/replay;
atomic rollback; scoped explicit user aliases and owned fork turns; strict wire
authority; same-source terminal output conflicts; fresh repeated qualification;
pruning followed by late approval resolution/replay and preserved summary;
current canonical gate verification; and content-free CLI failures. Scoped Ruff
and type checks also passed.

Retained local check evidence:
`.dev-tools/pytest-18da70e5cc2ac048-3667838-2a2ba210-details.txt`,
`.dev-tools/types-18da71050f8c8fa2-3672531-77e04db6-details.txt` and
`.dev-tools/ruff-18da7104eb11e1cb-3672533-adf6d6c9-details.txt`.
These are check artifacts, not deployment receipts. Full project acceptance,
packaged deployment, controlled deployed promotion/rollback, physical storage
fault recovery and production rates/latency require their own observed evidence.
