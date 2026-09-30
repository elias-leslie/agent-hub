# Native observation ledger v1

Agent Hub owns normalization, native command identity, source receipts and committed
positions. The v1 seam is additive and opt in: unchanged sessions continue through
the existing transcript endpoints, source IDs, byte checkpoints and query events.
The rollout adapter remains authoritative for timeline command projections. App
Server records enter a shadow ledger and never append timeline commands.

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
`collector_attested`, not independently reread evidence. This first slice supports
one rollout ledger per session; source rotation requires a later explicit contract.

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
Active-resume snapshots always remain provisional even if a producer claims durable
IDs. No content, position, ID spelling, wrapper call ID or root runtime alias can
establish a canonical join. Unresolved snapshots create no competing query work.
Inherited observations remain tagged receipts and cannot create child command
entities. A child that shares a parent's runtime alias keeps its own thread and
separate parent relationship. Omitted lineage fields do not overwrite session
lineage. Existing fork history exclusion remains the rollout parser's responsibility.

Matching durable final command observations link to one entity and the existing
rollout tool-use/result pair. Later observations cannot rewind terminal state or
append a second pair. Contradictory canonical command/cwd/exit or terminal state
creates an issue. Differently structured output streams remain separate receipt
evidence; this slice does not claim output equivalence. Wrapper call IDs remain
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
The installed contract is `codex-cli 0.159.2`, stdio JSON-RPC, with combined generated
ServerNotification/ServerRequest schema SHA-256
`6f7a929fad56ae9fc103a8364f0a7f51bd520c007b826d8e3edf5fe167c253e2`.
Both owner and authority validate this pinned contract. Upgrade requires regenerated
protocol assets, review, and a passing local conformance canary.

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
the collector never normalizes these into canonical events. `approval_response`
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
and one rollout projection pair. Native argv versus shell display text and local
file-URI cwd representations are normalized only inside Agent Hub. Equivalent
rollout native and tool wrappers do not append duplicate command pairs.

Approvals resolve against an earlier validated request from the same source,
connection, exact JSON-typed request ID and managed thread. Responses additionally
bind the original turn/item. `serverRequest/resolved` proves the request was cleared;
it does not prove approval. Usage notifications remain cumulative snapshots and do
not add a second token delta or billing source. Requested/configured model receipts
retain their evidence category; none proves delivered model. `observed_model` stays
null. Read/resume/fork responses remain snapshots, with no inherited command replay.
Native child ownership comes from verified spawn evidence; child live subscription
is not automatic and the missing subscription is an explicit health gap.

`GET /api/session-ingestion/sessions/{thread}/native-capture` exposes content-free
DB health under existing project authorization, without contacting App Server.
Internal execution-owner queries at `.../native-sources/{source}/observations` and
`.../issues` retrieve original receipts, conflicts and derived approval subjects
with bounded pagination and project/source authorization. All downstream queries,
rollout ingestion, backfill and checkpoints continue without App Server availability.

## Verification and promotion limits

The installed binary passed a controlled canary in a user/network namespace with
no external interfaces, no credentials and a scripted loopback Responses provider.
It exercised commands, approval request/client response/request clearance,
interruption, owned restart/resume, compaction, fork snapshots, native children,
usage and disabling capture while keeping the native connection alive. The actual
toy outbox and rollouts then passed isolated PostgreSQL reconciliation with source
registration both before and after ingestion. Tests also cover atomic rollback,
concurrent duplicate receipts, replay conflicts, missing positions, stale/future
acknowledgements, downtime/lost responses, leases, quota and unsupported contracts.

**Promotion remains shadow-only and default-off.** Rollout remains canonical for
timeline ordering and usage. Live ledger command identity is implemented, but live
timeline projection has not been promoted: its numeric turn/sequence allocation
must be reconciled with existing rollout user/lifecycle positions before it can
precede rollout safely. Provisional `item-*` receipts remain explicit unresolved
evidence and cannot be joined to UUIDs from content, ordinal position or ID spelling.
No attributable alias mapping was established by this pinned runtime canary.
This avoids duplicates but does not claim a proven provisional-to-durable join.
Full non-command canonical projections, source rotation, physical power-loss/disk
fault recovery, real deployed outage recovery and production shadow rates/latency
remain unproven. Promotion requires these identity/ordering acceptance gaps to close;
there is intentionally no configuration switch that bypasses them. Rollout remains
permanently available. See SummitFlow's `docs/architecture/managed-codex-sessions.md`
for configuration, delivery, rollback and the retained content-free canary receipt.
