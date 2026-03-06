# Session Ingestion Convergence Plan

## Goal

Converge Codex, Claude Code, native Agent Hub agents, and future agentic CLIs onto one repeatable session ingestion model:

1. `upsert_session`
2. `append_normalized_events`
3. `finalize_session`

Provider-specific code should only translate raw provider output into normalized events. All artifact extraction and persistence should happen once in Agent Hub.

Applied: [M:c37d31f2] [M:d301ef61]

## Target Architecture

### Canonical Session Contract

Every provider integration should use the same backend contract:

1. `upsert_session`
   - idempotent
   - creates or updates session metadata
   - fields:
     - `session_id`
     - `project_id`
     - `provider`
     - `model`
     - `session_type`
     - `cwd`
     - optional `provider_metadata`

2. `append_normalized_events`
   - idempotent append/upsert of ordered events
   - fields:
     - `session_id`
     - `turn`
     - `sequence`
     - `event_type`
     - `role`
     - `content`
     - `tool_name`
     - `tool_input`
     - `tool_output`
     - `timestamp`
     - `provider_event_id` or source checkpoint

3. `finalize_session`
   - idempotent
   - extracts artifacts from normalized events
   - stores:
     - citations
     - feedback items
     - summaries
     - analytics metrics

### Canonical Event Types

Keep one internal event vocabulary:

- `user_message`
- `assistant_message`
- `thinking`
- `tool_use`
- `tool_result`
- `memory_inject`
- `memory_cite`
- `error`
- `system_message`
- optional:
  - `session_boundary`
  - `context_compacted`
  - `subagent_result`

### Canonical Landing Tables

Keep current tables as the durable storage model:

- `sessions`
- `session_events`
- `feedback_items`

These are already the correct long-term landing zones.

## Current State

### Agent Hub Native Agents

Status: closest to target.

Current behavior:
- writes normalized events directly through:
  - `backend/app/api/complete/tool_event_storage.py`
  - `backend/app/api/complete/streaming_persistence.py`
  - `backend/app/services/event_storage.py`
- persists session state directly in Agent Hub
- already uses backend-native session lifecycle

Gap:
- finalize logic is still partially split between streaming paths and `session_analysis`
- contract is implicit rather than formalized as one ingestion service

### Claude Code

Status: functional but too much logic lives in hooks.

Current behavior:
- `~/.claude/hooks/PostToolUse.sh` records selected tool events
- `~/.claude/hooks/Stop.sh`:
  - resolves transcript paths
  - scans transcript for citations/feedback/summaries
  - calls analyze endpoint
  - closes session

Gap:
- hook contains artifact extraction logic that should belong in Agent Hub
- provider-specific orchestration is doing more than normalization

### Codex

Status: functional, but currently transcript-sync driven.

Current behavior:
- `~/summitflow/scripts/codex-session-sync.py` scans changed transcripts
- syncs transcript analysis into Agent Hub
- old process-exit shim still exists at `~/.codex/hooks/codex-session-stop.sh`
- periodic timer is currently the reliable path

Gap:
- transcript sync still works at transcript level rather than normalized event ingestion
- no formal checkpoint table in Agent Hub
- no first-class session boundary semantics for `/resume`

### Future Providers / CLIs

Status: no standard onboarding contract yet.

Gap:
- a future CLI could easily reintroduce bespoke parsing/finalization logic
- there is no explicit adapter interface for new providers

## Gaps Against Target

### Gap 1: No Explicit Ingestion Service

Current state:
- session creation, event storage, and analysis are spread across multiple modules and external scripts

Target:
- one backend ingestion service with explicit operations:
  - `upsert_session`
  - `append_events`
  - `finalize_session`

### Gap 2: Transcript Parsing Is Still a Primary Provider Path

Current state:
- Claude and Codex still rely on transcript scanning to derive artifacts

Target:
- transcripts are only adapter/bootstrap inputs
- normalized `session_events` become the primary internal source of truth

### Gap 3: No Standard Checkpointing for External Session Sources

Current state:
- Codex rescans transcript files and relies on idempotent finalization
- Claude Stop hook performs one-shot close-time scanning

Target:
- checkpoint ingestion by source/session:
  - external session id
  - transcript path or event source id
  - last processed offset / line / event id
  - last finalized checkpoint

### Gap 4: Session Boundary Semantics Are Weak

Current state:
- `/resume`, compaction, and intra-process reopen are inferred indirectly

Target:
- explicit boundary events:
  - `opened`
  - `resumed`
  - `compacted`
  - `finalized`

### Gap 5: Provider Adapters Are Not Thin Enough

Current state:
- Claude Stop hook and Codex sync worker both contain provider-specific orchestration and artifact assumptions

Target:
- provider adapters only translate raw provider events/transcripts into normalized events

## Phase Plan

## Phase 1: Formalize Backend Ingestion Contract

Objective:
- create one explicit ingestion service in Agent Hub

Deliverables:
- new backend module, likely under:
  - `backend/app/services/session_ingestion/`
- explicit operations:
  - `upsert_session(...)`
  - `append_normalized_events(...)`
  - `finalize_session(...)`

Suggested files:
- `backend/app/services/session_ingestion/service.py`
- `backend/app/services/session_ingestion/models.py`
- `backend/app/services/session_ingestion/checkpoints.py`
- `backend/app/api/session_ingestion.py`

Acceptance criteria:
- native Agent Hub code can call ingestion service instead of directly stitching pieces together
- ingestion API is provider-agnostic
- finalize is safe to re-run

## Phase 2: Introduce Provider Adapter Interface

Objective:
- define a standard provider adapter interface for any external session source

Deliverables:
- adapter interface like:
  - `discover_sessions()`
  - `build_session_metadata()`
  - `read_new_events(checkpoint)`
  - `detect_boundaries()`
  - `checkpoint_of(batch)`

Suggested files:
- `backend/app/services/session_ingestion/adapters/base.py`
- `backend/app/services/session_ingestion/adapters/claude_code.py`
- `backend/app/services/session_ingestion/adapters/codex.py`

Acceptance criteria:
- adding a provider does not require changes to artifact extraction logic
- provider modules are translation-only

## Phase 3: Move Transcript Parsing Behind Adapters

Objective:
- demote transcript parsing from a primary application flow to an adapter concern

Deliverables:
- `summary_transcript.py` logic split into provider adapters or shared adapter helpers
- transcript readers output normalized events instead of directly feeding analysis

Suggested files to refactor:
- `backend/app/services/memory/summary_transcript.py`
- move provider-specific parsing to:
  - `backend/app/services/session_ingestion/adapters/transcript_parsers/claude_code.py`
  - `backend/app/services/session_ingestion/adapters/transcript_parsers/codex.py`

Acceptance criteria:
- transcript parsing produces normalized events
- `session_analysis` no longer needs transcript-aware provider branching as a primary path

## Phase 4: Make Normalized Events the Primary Artifact Source

Objective:
- extract citations, feedback, and summaries primarily from `session_events`

Deliverables:
- central extractor that scans normalized assistant messages and boundary events
- transcript scanning retained only for backfill/bootstrap

Suggested files:
- `backend/app/services/session_ingestion/finalizer.py`
- `backend/app/services/session_ingestion/extractors.py`

Refactor targets:
- `backend/app/services/memory/session_analysis.py`
- `backend/app/services/memory/session_queries.py`

Acceptance criteria:
- citations, feedback, and summaries are extracted from normalized events first
- transcript path becomes optional fallback only

## Phase 5: Add External Ingestion Checkpoints

Objective:
- support efficient incremental ingestion and replay for external providers

Deliverables:
- new DB table, example:
  - `session_ingestion_checkpoints`

Recommended columns:
- `id`
- `provider`
- `external_session_id`
- `source_id`
- `session_id`
- `last_offset`
- `last_event_id`
- `last_finalized_offset`
- `updated_at`

Implementation requirements:
- add Alembic migration
- add checkpoint read/write service

Acceptance criteria:
- Codex and Claude adapters can ingest incrementally without broad rescans
- replay is deterministic

## Phase 6: Add Explicit Session Boundary Events

Objective:
- make `/resume`, compaction, and finalize explicit

Deliverables:
- new normalized event type or structured tool metadata for:
  - `opened`
  - `resumed`
  - `compacted`
  - `finalized`

Acceptance criteria:
- resumed sessions can be segmented cleanly
- close/finalize no longer depends on provider-specific heuristics

## Phase 7: Migrate Claude Code Integration

Objective:
- reduce Claude hook responsibilities to adapter/bootstrap only

Changes:
- `~/.claude/hooks/Stop.sh`
  - stop scanning citations/feedback/summaries directly
  - only deliver transcript metadata or raw source info to Agent Hub
- Agent Hub Claude adapter:
  - reads transcript incrementally
  - appends normalized events
  - finalizes centrally

Acceptance criteria:
- Claude hook no longer contains artifact extraction logic
- Claude ingestion matches Codex ingestion model structurally

## Phase 8: Migrate Codex Integration

Objective:
- keep timer-based delivery if needed, but move it to normalized-event ingestion

Changes:
- `~/summitflow/scripts/codex-session-sync.py`
  - stop calling transcript-aware analyze as the primary action
  - instead:
    - upsert session
    - append normalized events from new transcript chunks
    - finalize centrally
- old process-exit shim remains optional backup until confidence is high

Acceptance criteria:
- Codex no longer depends on transcript-wide artifact scanning as the primary flow
- `/resume` works because boundaries and incremental events are captured

## Phase 9: Make Native Agent Hub Use the Same Ingestion Service

Objective:
- native sessions become the reference implementation for the same backend contract

Changes:
- route native event writes through the formal ingestion service
- keep direct writes if needed initially, but behind one service boundary

Acceptance criteria:
- external and native sessions share one persistence/finalize abstraction

## Phase 10: Standardize Provider Onboarding

Objective:
- future providers are cheap to add and cannot bypass the model

Deliverables:
- provider adapter checklist
- required tests
- onboarding template

Acceptance criteria:
- adding Gemini CLI, OpenRouter CLI, or another agentic tool only requires:
  - adapter implementation
  - checkpoint support
  - provider metadata mapping

## Execution Order

Recommended order:

1. Phase 1
2. Phase 2
3. Phase 5
4. Phase 3
5. Phase 4
6. Phase 6
7. Phase 7
8. Phase 8
9. Phase 9
10. Phase 10

Reason:
- establish the backend contract first
- add checkpointing before deep provider migration
- migrate providers only after the canonical ingestion path exists

## What Can Stay

Keep:
- `sessions`
- `session_events`
- `feedback_items`
- current native event storage helpers
- current session summary fields on `sessions`

These are already the right storage primitives.

## What Should Be Replaced or Thinned

Replace or reduce:
- transcript-heavy logic in `~/.claude/hooks/Stop.sh`
- transcript-heavy primary flow in `~/summitflow/scripts/codex-session-sync.py`
- transcript-first assumptions in `session_analysis`

Keep transcript parsing only as:
- bootstrap
- replay
- fallback

## Acceptance Criteria For Full Convergence

The architecture is converged when:

1. Agent Hub native, Claude Code, and Codex all use the same backend ingestion contract.
2. Citations, feedback, and summaries are extracted centrally from normalized events.
3. Transcript parsing is not a primary provider-specific persistence path.
4. Re-running finalize is safe and does not duplicate citations or feedback.
5. A new provider can be added without touching:
   - citation persistence
   - feedback persistence
   - summary persistence
   - analytics storage logic

## Proposed First Implementation Batch

Lowest-risk first batch:

1. Phase 1: add formal ingestion service
2. Phase 2: add adapter interface
3. Phase 5: add checkpoint table and service
4. Partial Phase 8: refactor Codex sync to append normalized events incrementally

Why this batch first:
- Codex is currently the least native path
- recent bugs already exposed its boundary issues
- checkpointing plus normalized events gives immediate architectural payoff without rewriting native Agent Hub flow first

## Risks

- provider transcript formats may drift
- boundary detection may remain imperfect until explicit provider hooks exist
- migration will require careful idempotency handling for old sessions
- provider-side scripts may need a temporary dual path during rollout

These are manageable if the backend contract lands first.

## Non-Goals

Do not add:
- message buses
- Kafka
- plugin frameworks
- complex distributed ingestion infrastructure

This should remain:
- one DB
- one ingestion service
- one finalizer
- thin provider adapters

Applied: [M:6a2ceb1c] [G:4a453ef9]
