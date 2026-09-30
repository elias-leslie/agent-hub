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

## Remaining Architecture D stages

Managed App Server supervision and durable spool are deferred. Existing supervision
has not demonstrated the required crash recovery, capture gap, approval intent and
single-owner fencing semantics; this ledger does not imply those guarantees.
Next is an isolated opted-in managed capture that durably spools before forwarding,
retains rollout reconciliation and measures end-to-end commit latency and gaps.
Before promotion, prove process/epoch fencing, lost acknowledgments and collector
restart, fork/root lineage and usage-scope conformance, partial transient approval
history, provider version/schema negotiation, and explicit health/completeness.
Remote forwarding, live-only approval capture, provisional-ID correlation,
non-command projections, rollout ledger rotation and managed push promotion remain
separate bounded stages. External discovery/backfill and rollout polling stay active.
