# Unified Design: Shared Artifact Hub + Autonomous Business Operations

**Status:** Draft — Discussion
**Date:** 2026-03-14
**Scope:** Agent-Hub, SummitFlow, Portfolio-AI, A-Term

---

## Table of Contents

1. [Artifact Hub Architecture](#1-artifact-hub-architecture)
2. [Migration Plan](#2-migration-plan)
3. [Autonomous Ops Agent Architecture](#3-autonomous-ops-agent-architecture)
4. [Integration with Existing Benchmarks](#4-integration-with-existing-benchmarks)
5. [Recurring Schedule & Trigger Model](#5-recurring-schedule--trigger-model)
6. [Escalation & Approval Workflow](#6-escalation--approval-workflow)
7. [Idea Pipeline Design](#7-idea-pipeline-design)
8. [Gap Analysis](#8-gap-analysis)
9. [Phased Rollout](#9-phased-rollout)
10. [Holistic Integration](#10-holistic-integration)

---

## 1. Artifact Hub Architecture

### 1.1 Service Location: Module within Agent-Hub

The Artifact Hub lives as a new module inside Agent-Hub (not a standalone microservice).

**Justification:**
- Agent-Hub already owns auth (API keys, clients, project permissions), 32 routers, and is the central dependency for all projects.
- All agent workflows run through `complete_internal()` — artifact creation is a storage call added to existing flows.
- SummitFlow, Portfolio-AI, and A-Term already make HTTP calls to Agent-Hub. Same pattern, new endpoints.
- No independent scaling need — we're on a single server with Docker containers sharing a volume.

**New components:**
- 2 new FastAPI routers (`/api/artifacts`, `/api/artifact-permissions`)
- 1 new service (`ArtifactService`)
- 1 new storage backend abstraction (`StorageBackend`)
- 3 new database tables
- 1 new shared React package (`@agent-hub/artifact-panel`)

### 1.2 Data Model

```sql
-- Core artifact record
CREATE TABLE artifacts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id      TEXT,                    -- NULL = global artifact
    artifact_type   VARCHAR(50) NOT NULL,    -- note, image, document, diagram, plan,
                                             -- prompt, research, experiment_log, screenshot,
                                             -- mockup, design_asset, analysis, idea
    title           VARCHAR(500) NOT NULL,
    description     TEXT,
    tags            TEXT[] DEFAULT '{}',

    -- Authorship
    author_type     VARCHAR(20) NOT NULL,    -- human, agent
    author_id       VARCHAR(100) NOT NULL,   -- user identifier or agent slug

    -- Content (text-based artifacts get full-text search)
    content_text    TEXT,                     -- notes, plans, research — searchable
    storage_key     VARCHAR(1000),           -- for binary files — relative path under storage root
    content_type    VARCHAR(200),            -- MIME type
    file_size       BIGINT,                  -- bytes

    -- Linking
    parent_id       UUID REFERENCES artifacts(id) ON DELETE SET NULL,  -- for variants/derivatives
    session_id      VARCHAR(100),            -- link to originating session
    source_project  VARCHAR(100),            -- which project created this

    -- Extensible
    metadata        JSONB DEFAULT '{}',

    -- Lifecycle
    status          VARCHAR(20) DEFAULT 'active',  -- active, archived, deleted
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_artifacts_project ON artifacts(project_id);
CREATE INDEX idx_artifacts_type ON artifacts(project_id, artifact_type);
CREATE INDEX idx_artifacts_tags ON artifacts USING GIN(tags);
CREATE INDEX idx_artifacts_author ON artifacts(author_type, author_id);
CREATE INDEX idx_artifacts_status ON artifacts(status) WHERE status = 'active';
CREATE INDEX idx_artifacts_search ON artifacts USING GIN(to_tsvector('english', coalesce(title, '') || ' ' || coalesce(content_text, '')));
CREATE INDEX idx_artifacts_created ON artifacts(created_at DESC);
CREATE INDEX idx_artifacts_parent ON artifacts(parent_id) WHERE parent_id IS NOT NULL;
CREATE INDEX idx_artifacts_source ON artifacts(source_project);

-- Version history (for text-based artifacts: notes, plans, specs, prompts)
CREATE TABLE artifact_versions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    artifact_id     UUID NOT NULL REFERENCES artifacts(id) ON DELETE CASCADE,
    version_number  INT NOT NULL,
    content_text    TEXT,
    storage_key     VARCHAR(1000),
    change_summary  TEXT,
    created_by_type VARCHAR(20) NOT NULL,    -- human, agent
    created_by_id   VARCHAR(100) NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(artifact_id, version_number)
);

CREATE INDEX idx_artifact_versions_artifact ON artifact_versions(artifact_id, version_number DESC);

-- Lightweight RBAC
CREATE TABLE artifact_permissions (
    id              SERIAL PRIMARY KEY,
    -- Scope: which artifacts does this apply to?
    project_id      TEXT,                    -- NULL = all projects
    artifact_id     UUID REFERENCES artifacts(id) ON DELETE CASCADE,  -- NULL = project-wide default

    -- Grantee: who gets this access?
    grantee_type    VARCHAR(20) NOT NULL,    -- agent, project, role
    grantee_id      VARCHAR(100) NOT NULL,   -- agent slug, project ID, or role name

    -- Access
    access_level    VARCHAR(10) NOT NULL,    -- read, write, none

    created_at      TIMESTAMPTZ DEFAULT now(),
    UNIQUE(project_id, artifact_id, grantee_type, grantee_id)
);
```

**Design decisions:**
- `project_id = NULL` means global (visible everywhere). Non-null scopes to that project.
- `content_text` stores searchable text inline. Binary files use `storage_key`.
- `parent_id` supports variant chains (like SummitFlow's `source_asset_id`).
- Full-text search via PostgreSQL `to_tsvector` — no Elasticsearch needed at this scale.
- Human always has full access (enforced in the service layer, not the permission table).

### 1.3 Binary Storage Backend

**Recommendation: Local filesystem with Docker shared volume, behind a `StorageBackend` abstraction.**

```python
# backend/app/services/artifact_storage.py

class StorageBackend(Protocol):
    async def save(self, key: str, data: bytes, content_type: str) -> str: ...
    async def get(self, key: str) -> bytes: ...
    async def delete(self, key: str) -> None: ...
    def get_url(self, key: str) -> str: ...

class LocalStorageBackend:
    """Filesystem storage under a configurable root directory."""

    def __init__(self, root: Path):
        self.root = root

    async def save(self, key: str, data: bytes, content_type: str) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    async def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    async def delete(self, key: str) -> None:
        path = self.root / key
        if path.exists():
            path.unlink()

    def get_url(self, key: str) -> str:
        return f"/api/artifacts/content/{key}"
```

**Storage key structure:** `{project_id or "global"}/{artifact_type}/{YYYY-MM}/{uuid}.{ext}`

Example: `summitflow/image/2026-03/a1b2c3d4.png`

**Why local filesystem:**
- Single server with Docker — shared volume mount (`/data/artifacts`) accessible by all containers.
- SummitFlow and Portfolio-AI already use filesystem storage successfully.
- Zero new infrastructure. The `StorageBackend` protocol allows a future swap to MinIO/S3 by implementing a new class — no other code changes.

**Docker compose volume:**
```yaml
volumes:
  artifact-storage:
    driver: local

services:
  agent-hub:
    volumes:
      - artifact-storage:/data/artifacts
  summitflow:
    volumes:
      - artifact-storage:/data/artifacts:ro  # read-only from non-owner services
  portfolio-ai:
    volumes:
      - artifact-storage:/data/artifacts:ro
```

### 1.4 REST API

```
# Core CRUD
POST   /api/artifacts                           # Create artifact (multipart or JSON)
GET    /api/artifacts                           # List/search artifacts (query params below)
GET    /api/artifacts/{id}                      # Get artifact metadata
GET    /api/artifacts/{id}/content              # Get/stream binary content
PUT    /api/artifacts/{id}                      # Update metadata or text content
DELETE /api/artifacts/{id}                      # Soft-delete (set status=deleted)

# Versioning
GET    /api/artifacts/{id}/versions             # List versions
GET    /api/artifacts/{id}/versions/{version}   # Get specific version

# Binary content serving (for storage keys)
GET    /api/artifacts/content/{key:path}        # Serve binary by storage key

# Permissions
GET    /api/artifact-permissions                # List permissions
POST   /api/artifact-permissions                # Create permission rule
DELETE /api/artifact-permissions/{id}           # Remove permission rule

# Quick upload (drop zone)
POST   /api/artifacts/upload                    # Simplified upload — file + optional tags/title
```

**Search/filter query params on `GET /api/artifacts`:**
```
?project_id=       # filter by project (omit for all, "global" for global-only)
&type=             # artifact_type
&tags=             # comma-separated, AND match
&author_type=      # human or agent
&author_id=        # specific author
&source_project=   # which project created it
&q=                # full-text search across title + content_text
&status=active     # default active, can request archived
&sort=created_at   # created_at, updated_at, title
&order=desc
&limit=50
&offset=0
```

### 1.5 Permissions Model

**Rules (evaluated in order):**
1. Human user → full access always (hardcoded, no DB check).
2. Check `artifact_permissions` for matching `(project_id, artifact_id, grantee_type, grantee_id)`.
3. Most specific match wins: artifact-level > project-level > global default.
4. No matching rule → default **read** access (agents can read by default, must be explicitly granted write or denied).

**Default seeded permissions:**
```
+- Persona and core agents get full write access
(NULL, NULL, 'agent', 'persona',    'write')
(NULL, NULL, 'agent', 'coder',      'write')
(NULL, NULL, 'agent', 'critic',     'write')
(NULL, NULL, 'agent', 'analyst',    'write')
(NULL, NULL, 'agent', 'designer',   'write')
(NULL, NULL, 'agent', 'supervisor', 'read')   -- review only
```

### 1.6 UI Integration Pattern

**Package: `@agent-hub/artifact-panel`**

Lives at `/home/kasadis/agent-hub/packages/artifact-panel/`, following the exact pattern of `passport-client` and `chat-ui`.

**Exports:**
```typescript
// Components
export { ArtifactPanel }        // Full panel with search, list, viewer, upload
export { ArtifactBrowser }      // List/grid view with filters
export { ArtifactViewer }       // Single artifact viewer (text, image, markdown)
export { ArtifactDropZone }     // Drag-and-drop upload area
export { ArtifactSearch }       // Search bar with filter controls

// Hooks
export { useArtifacts }         // List/search artifacts (react-query)
export { useArtifact }          // Get single artifact
export { useArtifactUpload }    // Upload mutation
export { useArtifactActions }   // Update, delete, version operations

// Types
export type { Artifact, ArtifactType, ArtifactVersion, ArtifactPermission }
export type { ArtifactPanelProps, ArtifactBrowserProps }
```

**Integration per project:**

```typescript
// Agent-Hub — full panel in sidebar or dedicated page
import { ArtifactPanel } from '@agent-hub/artifact-panel';
<ArtifactPanel
  agentHubUrl={AGENT_HUB_URL}
  projectId="agent-hub"         // scoped view
  showGlobal={true}             // also show global artifacts
  authorContext={{ type: 'human', id: 'kasadis' }}
/>

// SummitFlow — integrated in design workspace
import { ArtifactBrowser, ArtifactDropZone } from '@agent-hub/artifact-panel';
<ArtifactBrowser
  agentHubUrl={AGENT_HUB_URL}
  projectId={currentProject.id}
  types={['design_asset', 'mockup', 'diagram', 'plan']}
/>

// Portfolio-AI — research documents and screenshots
import { ArtifactBrowser } from '@agent-hub/artifact-panel';
<ArtifactBrowser
  agentHubUrl={AGENT_HUB_URL}
  projectId="portfolio-ai"
  types={['research', 'screenshot', 'analysis', 'document']}
/>

// A-Term — upload and browse from the A-Term UI
import { ArtifactDropZone, ArtifactBrowser } from '@agent-hub/artifact-panel';
// Accessible via a slide-out panel or tab
```

**Configuration pattern:** Each consuming app passes `agentHubUrl` as a prop. The panel handles all API calls internally using that base URL. No duplicated API client logic.

**Future projects:** Import the package, pass the URL and project context. 5 minutes to integrate.

### 1.7 Agent Workflow Integration

Agents interact with artifacts through tool calls during `complete_internal()`:

```python
# New tools available to agents during completion
ARTIFACT_TOOLS = [
    {
        "name": "create_artifact",
        "description": "Create and store an artifact (note, plan, research output, diagram, etc.)",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "artifact_type": {"type": "string"},
                "content": {"type": "string"},  # text content or base64 for small files
                "tags": {"type": "array", "items": {"type": "string"}},
                "project_id": {"type": "string", "description": "null for global"},
            },
            "required": ["title", "artifact_type", "content"]
        }
    },
    {
        "name": "search_artifacts",
        "description": "Search existing artifacts by query, type, tags, or project",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "artifact_type": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "project_id": {"type": "string"},
            }
        }
    },
    {
        "name": "get_artifact",
        "description": "Retrieve an artifact's content by ID",
        "input_schema": {
            "type": "object",
            "properties": {"artifact_id": {"type": "string"}},
            "required": ["artifact_id"]
        }
    },
    {
        "name": "update_artifact",
        "description": "Update an existing artifact's content (creates a new version)",
        "input_schema": {
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "content": {"type": "string"},
                "change_summary": {"type": "string"},
            },
            "required": ["artifact_id", "content"]
        }
    }
]
```

These tools are registered in the tool execution layer alongside existing tools. Project/runtime policy controls access — write-capable runs get create/update tools; read-only runs only get search/get.

---

## 2. Migration Plan

### 2.1 SummitFlow Design Assets → Artifact Hub

**Approach:** Dual-write during transition, then redirect reads.

**Phase 1 — Dual-write (non-breaking):**
- Modify `design_asset_pipeline.py`: after saving to SummitFlow's `design_assets` table and filesystem, also POST to Agent-Hub's `/api/artifacts` endpoint.
- Artifact metadata: `artifact_type=design_asset`, `source_project=summitflow`, `metadata` carries SummitFlow-specific fields (asset_type, workflow, status, prompt, etc.).
- Binary files: uploaded via multipart to artifact endpoint, stored in shared volume.
- SummitFlow's existing UI continues reading from its own DB — zero disruption.

**Phase 2 — Unified read:**
- SummitFlow's design workspace adds `ArtifactBrowser` panel alongside existing asset studio.
- Users can browse both legacy and Hub artifacts.
- New assets created through either path are visible in both.

**Phase 3 — Redirect (optional, later):**
- If dual storage proves wasteful, redirect SummitFlow's asset creation to go through the Artifact Hub API only, with SummitFlow's `design_assets` table becoming a lightweight cache/index.
- This is optional — dual-write with a shared volume is cheap.

**What NOT to migrate:** SummitFlow's design standards and rules tables stay in SummitFlow. They're project configuration, not artifacts.

### 2.2 Portfolio-AI Documents → Artifact Hub

**Approach:** Proxy new uploads through the Hub; backfill existing.

**Phase 1 — New uploads go to Hub:**
- Modify `household_document_pipeline.py`: on upload, POST the file to `/api/artifacts` with `artifact_type=document`, `source_project=portfolio-ai`, then store the returned artifact ID in `household_documents.metadata`.
- Portfolio-AI keeps its own document processing pipeline (review, extraction, classification) — those are domain-specific and stay local.
- The Hub stores the raw file; Portfolio-AI stores the extracted intelligence.

**Phase 2 — Backfill:**
- Script to iterate existing `household_documents` and `data/artifacts/` directory, creating corresponding artifact records in the Hub.
- Idempotent via content hash matching.

**Phase 3 — Research artifacts:**
- Move `data/artifacts/` (screenshots, evidence.json) into the Hub as `artifact_type=research` and `artifact_type=screenshot`.
- Watchlist narratives stored as `artifact_type=analysis`.

### 2.3 A-Term File Uploads

- Modify A-Term's `files.py` upload endpoint to optionally forward to the Artifact Hub.
- Add the `ArtifactBrowser` component as a slide-out panel in A-Term's UI.
- Low priority — A-Term's file uploads are transient by nature.

---

## 3. Autonomous Ops Agent Architecture

### 3.1 New Specialist Agents

Add these to the agent registry (seed_data.json):

```
Agent Slug             Primary Model        Role
─────────────────────  ───────────────────  ────────────────────────────────────
market-researcher      claude-sonnet-4.6    Market analysis, competitor tracking,
                                            trend identification, pricing research

business-developer     claude-sonnet-4.6    Revenue stream identification, lead
                                            generation, outreach draft creation,
                                            partnership opportunities

strategist             claude-opus-4.6      Business planning, prioritization,
                                            strategic analysis, decision frameworks,
                                            opportunity evaluation

content-creator        claude-sonnet-4.6    Marketing copy, blog posts, social
                                            media, landing page content, pitch decks

idea-researcher        claude-sonnet-4.6    Deep-dive research on specific ideas,
                                            feasibility analysis, competitive
                                            landscape for a given concept
```

**Existing agents that participate in business ops (no changes needed):**
- `persona` (display-name configurable) — orchestrator, dispatches to specialists
- `equity-analyst` — portfolio/investment research
- `critic` — reviews and critiques any agent's output
- `supervisor` — completion review
- `analyst` — can be used for technical feasibility analysis
- `designer` — creative work, UI mockups
- `coder` — technical prototyping

### 3.2 Coordination Model

The persona agent is the orchestrator. It does not do the research itself; it dispatches to specialists and reviews their output.

```
Persona heartbeat (every 60 min by default)
│
├── Check business ops schedule (see §5)
│   ├── Is market research due? → Dispatch market-researcher
│   ├── Is BD cycle due? → Dispatch business-developer
│   ├── Are there ideas in the pipeline? → Dispatch idea-researcher
│   ├── Is content needed? → Dispatch content-creator
│   └── Is strategic review due? → Dispatch strategist
│
├── Review completed specialist outputs
│   ├── Critic agent audits quality
│   ├── Persona decides: promote / revise / archive
│   └── Results stored as artifacts in the Hub
│
└── Escalate if needed (see §6)
```

**Dispatch mechanism:** The persona uses `complete_internal()` with the appropriate `agent_slug` to invoke specialists. Each specialist produces structured output stored as an artifact. The persona then reviews via the existing supervisor/critic pipeline.

### 3.3 The Autoresearch Loop (Adapted for Business)

```
┌─────────────────────────────────────────────────────────────┐
│                    Business Experiment Loop                   │
│                                                              │
│  1. HYPOTHESIZE                                              │
│     Agent generates a business hypothesis:                   │
│     "Revenue opportunity: Offer Agent-Hub as a managed       │
│      service for small dev teams at $49/mo"                  │
│     → Stored as artifact (type: idea, status: hypothesis)    │
│                                                              │
│  2. RESEARCH                                                 │
│     market-researcher + idea-researcher execute:             │
│     - Market size estimation                                 │
│     - Competitor analysis                                    │
│     - Pricing benchmarks                                     │
│     - Target customer profiling                              │
│     → Stored as artifacts (type: research, linked to idea)   │
│                                                              │
│  3. VALIDATE                                                 │
│     critic + strategist evaluate:                            │
│     - Score confidence (0-100) on multiple dimensions:       │
│       market_size, feasibility, competitive_advantage,       │
│       revenue_potential, effort_required                     │
│     - Composite score computed                               │
│     → Stored as artifact (type: analysis, linked to idea)    │
│                                                              │
│  4. DECIDE                                                   │
│     If composite_score >= threshold (default 60):            │
│       → PROMOTE: move to idea pipeline (see §7)              │
│     Else:                                                    │
│       → ARCHIVE: store with reasoning, move to next          │
│                                                              │
│  5. REPEAT                                                   │
│     Loop runs on schedule. No human input needed.            │
│     Human returns to a log of evaluated ideas.               │
└─────────────────────────────────────────────────────────────┘
```

**Key adaptation from Karpathy's autoresearch:**
- Instead of modifying `train.py` → agents generate hypotheses
- Instead of a 5-minute training run → agents execute structured research (bounded to ~10 minutes per hypothesis)
- Instead of `val_bpb` → multi-dimensional quality scores
- Instead of git keep/discard → artifact promotion/archival in the Hub
- Instead of running indefinitely → runs on the persona heartbeat schedule (configurable cadence)

---

## 4. Integration with Existing Benchmarks

### 4.1 Shared Experiment Engine

The existing benchmark system and the business research loop share the same core pattern:

```
Hypothesize → Execute → Measure → Keep/Discard → Log → Repeat
```

**Architecture: Extract a shared `ExperimentEngine`, keep domain tables separate.**

```python
# backend/app/services/experiment_engine.py

class ExperimentRunner(Protocol):
    """Domain-specific experiment execution."""
    async def generate_hypothesis(self, context: dict) -> Hypothesis: ...
    async def execute(self, hypothesis: Hypothesis) -> ExecutionResult: ...
    async def score(self, result: ExecutionResult) -> dict[str, float]: ...
    async def decide(self, scores: dict[str, float], threshold: float) -> Decision: ...

class ExperimentEngine:
    """Shared loop logic — scheduling, iteration, logging, keep/discard."""

    def __init__(self, runner: ExperimentRunner, storage: ExperimentStorage):
        self.runner = runner
        self.storage = storage

    async def run_iteration(self, context: dict) -> IterationResult:
        hypothesis = await self.runner.generate_hypothesis(context)
        result = await self.runner.execute(hypothesis)
        scores = await self.runner.score(result)
        decision = await self.runner.decide(scores, context.get("threshold", 0.6))

        record = await self.storage.persist(hypothesis, result, scores, decision)
        return IterationResult(record=record, decision=decision)
```

**Two runners:**

1. **`AgentBenchmarkRunner`** — wraps existing `_run_experiment_and_decide()` logic.
   - Hypothesis: "This prompt change improves agent performance"
   - Execute: Run cohort benchmarks (baseline + candidate)
   - Score: composite_score, pass_rate from bootstrap CI
   - Decide: promote / rollback / hold

2. **`BusinessResearchRunner`** — new implementation for business ops.
   - Hypothesis: Business idea or strategy
   - Execute: Dispatch specialist agents for research
   - Score: multi-dimensional (market_size, feasibility, etc.)
   - Decide: promote to pipeline / archive

### 4.2 Business Experiment Tables (New, Separate)

```sql
-- Business experiment campaigns (analogous to agent_benchmark_experiments)
CREATE TABLE business_experiments (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_key  VARCHAR(200) UNIQUE NOT NULL,
    name            VARCHAR(500) NOT NULL,
    domain          VARCHAR(50) NOT NULL,     -- revenue, marketing, product, strategy, investment
    status          VARCHAR(20) DEFAULT 'open',  -- open, concluded
    decision        VARCHAR(20),              -- promote, archive, hold
    decision_reason TEXT,

    -- Hypothesis
    hypothesis      TEXT NOT NULL,
    hypothesis_source VARCHAR(50),            -- agent_generated, human_submitted

    -- Evidence (populated after research)
    evidence        JSONB DEFAULT '{}',       -- scores, research summaries, agent outputs

    -- Artifact links
    idea_artifact_id     UUID REFERENCES artifacts(id),
    research_artifact_ids UUID[] DEFAULT '{}',

    -- Tracking
    iteration_count INT DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT now(),
    concluded_at    TIMESTAMPTZ
);

-- Individual research attempts within an experiment
CREATE TABLE business_experiment_attempts (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id   UUID NOT NULL REFERENCES business_experiments(id) ON DELETE CASCADE,
    attempt_number  INT NOT NULL,

    -- Execution
    agent_slug      VARCHAR(50) NOT NULL,     -- which agent ran this
    session_id      VARCHAR(100),
    research_type   VARCHAR(50),              -- market_analysis, competitor_research,
                                              -- feasibility, financial_model, critique

    -- Scoring (domain-specific dimensions)
    scores          JSONB NOT NULL,           -- {market_size: 0.7, feasibility: 0.8, ...}
    composite_score FLOAT,
    passed          BOOLEAN,

    -- Output
    output_artifact_id UUID REFERENCES artifacts(id),
    summary         TEXT,

    -- Tracking
    latency_ms      INT,
    token_count     INT,
    created_at      TIMESTAMPTZ DEFAULT now(),

    UNIQUE(experiment_id, attempt_number)
);

CREATE INDEX idx_biz_exp_domain ON business_experiments(domain);
CREATE INDEX idx_biz_exp_status ON business_experiments(status);
CREATE INDEX idx_biz_exp_attempts ON business_experiment_attempts(experiment_id);
```

### 4.3 How They Connect

```
                    ExperimentEngine (shared logic)
                    ├── iteration loop
                    ├── scoring framework
                    ├── keep/discard protocol
                    └── structured logging
                         │
              ┌──────────┴──────────┐
              │                     │
    AgentBenchmarkRunner     BusinessResearchRunner
              │                     │
    ┌─────────┴─────────┐   ┌──────┴──────┐
    │ agent_benchmark_*  │   │ business_*  │
    │ tables (existing)  │   │ tables (new)│
    └────────────────────┘   └─────────────┘
```

Both feed results into the Artifact Hub for human review. Both use the same scoring normalization (0-1 scale). Both support regression clustering (existing `agent_regression_clusters` pattern extended to business domain).

---

## 5. Recurring Schedule & Trigger Model

### 5.1 Schedule Design

All autonomous ops run via the persona's existing infrastructure: **Hatchet cron tasks** + **`persona_scheduled_jobs`** table.

```
Job Name                    Cadence         Payload Type    Agent(s) Involved
──────────────────────────  ──────────────  ──────────────  ─────────────────────
market_research_cycle       weekly (Mon)    agent_turn      market-researcher, critic
business_dev_cycle          weekly (Wed)    agent_turn      business-developer, strategist
idea_pipeline_review        daily           agent_turn      idea-researcher, critic
content_creation_cycle      weekly (Fri)    agent_turn      content-creator, critic
strategic_review            bi-weekly       agent_turn      strategist
portfolio_research          daily           agent_turn      equity-analyst
experiment_loop             every 4h        agent_turn      (varies by experiment)
artifact_cleanup            weekly (Sun)    agent_turn      persona (housekeeping)
```

### 5.2 Implementation

These are seeded as `PersonaScheduledJob` rows:

```python
BUSINESS_OPS_SCHEDULE = [
    {
        "name": "market_research_cycle",
        "schedule_type": "cron",
        "schedule_value": "0 9 * * 1",           # Monday 9 AM
        "schedule_timezone": "America/New_York",
        "payload_type": "agent_turn",
        "payload_message": (
            "Run the weekly market research cycle. "
            "Dispatch market-researcher to analyze: "
            "1) Competitor updates for Agent-Hub, SummitFlow, Portfolio-AI, A-Term. "
            "2) Emerging trends in AI developer tools, autonomous agents, portfolio management. "
            "3) Pricing benchmarks for similar products. "
            "Store all findings as artifacts in the Hub. "
            "Have critic review the output before finalizing."
        ),
        "enabled": True,
    },
    {
        "name": "idea_pipeline_review",
        "schedule_type": "cron",
        "schedule_value": "0 10 * * *",           # Daily 10 AM
        "schedule_timezone": "America/New_York",
        "payload_type": "agent_turn",
        "payload_message": (
            "Review the idea pipeline. "
            "1) Check for new human-submitted ideas (artifacts tagged 'idea:new'). "
            "2) Pick the highest-priority unresearched idea and run one experiment loop iteration. "
            "3) If no pending ideas, generate 1-2 new hypotheses based on recent market research. "
            "4) Update idea pipeline artifacts with current status."
        ),
        "enabled": True,
    },
    # ... similar for other jobs
]
```

### 5.3 Trigger Model

```
Triggers:
├── Scheduled (cron)          — recurring ops on cadence above
├── Heartbeat-initiated       — Persona checks for due work during regular heartbeat
├── Human-initiated           — you submit an idea, request research, or trigger manually
├── Event-driven (future)     — webhook triggers (e.g., competitor releases new feature)
└── Experiment loop           — autonomous iteration on active experiments
```

The experiment loop is the only novel trigger. It's implemented as a Hatchet workflow that runs every 4 hours, picks up active `business_experiments` with `status=open`, and runs the next iteration for each.

---

## 6. Escalation & Approval Workflow

### 6.1 Escalation Rules

```python
ESCALATION_RULES = {
    # Never escalate — fully autonomous
    "research": "autonomous",
    "analysis": "autonomous",
    "idea_generation": "autonomous",
    "idea_critique": "autonomous",
    "content_drafting": "autonomous",
    "competitor_monitoring": "autonomous",
    "artifact_creation": "autonomous",
    "experiment_iteration": "autonomous",

    # Always escalate — requires human approval
    "publish_content": "always",          # Blog posts, social media, public-facing
    "external_outreach": "always",        # Emails, messages to real people
    "spend_money": "always",              # Ads, tools, subscriptions
    "create_accounts": "always",          # Sign up for services
    "modify_pricing": "always",           # Change product pricing
    "legal_or_contractual": "always",     # Agreements, terms, partnerships

    # Conditional — escalate based on confidence/cost
    "strategic_pivot": "if_confidence_below_70",
    "new_revenue_stream_launch": "if_confidence_below_80",
    "architecture_decision": "if_breaking_change",
}
```

### 6.2 Escalation Mechanism

When an agent hits an escalation trigger:

1. Create an artifact with `artifact_type=escalation`, tagged `escalation:pending`.
2. Send a push notification via the existing push system (`@agent-hub/push-client`).
3. The artifact contains: what needs deciding, agent's recommendation, confidence score, supporting research artifacts.
4. Human reviews in the Artifact Hub UI and marks as `escalation:approved` or `escalation:rejected`.
5. Next heartbeat picks up the resolution and continues.

```python
# Escalation artifact structure
{
    "artifact_type": "escalation",
    "title": "Approval needed: Launch donation page on GitHub Sponsors",
    "tags": ["escalation:pending", "domain:revenue"],
    "metadata": {
        "escalation_type": "publish_content",
        "agent_recommendation": "approve",
        "confidence": 0.85,
        "supporting_artifacts": ["uuid-1", "uuid-2"],
        "deadline": "2026-03-21T00:00:00Z",  # optional
        "auto_action_on_timeout": "none",     # none, approve, reject
    },
    "content_text": "## Context\n...\n## Recommendation\n...\n## Risk Assessment\n..."
}
```

---

## 7. Idea Pipeline Design

### 7.1 Bidirectional Flow

```
Human → Agents:
  1. Human creates artifact (type=idea, tags=['idea:new'])
     via any project's UI (ArtifactDropZone or direct create)
  2. Daily idea_pipeline_review job picks it up
  3. idea-researcher runs feasibility/market research
  4. critic reviews research quality
  5. strategist scores and recommends next steps
  6. Results linked back to original idea artifact

Agents → Human:
  1. Experiment loop generates hypothesis
  2. Research agents flesh it out
  3. If composite_score >= threshold → create artifact
     (type=idea, tags=['idea:agent-generated', 'idea:validated'])
  4. Push notification to human: "New validated idea ready for review"
  5. Human reviews, provides feedback, approves/rejects

Refinement Loop:
  1. Human feedback stored as artifact (type=note, parent_id=idea)
  2. Next cycle, agents incorporate feedback and re-research
  3. Iterate until idea is either promoted to "actionable" or archived
```

### 7.2 Idea Lifecycle

```
                     ┌─────────┐
                     │   NEW   │ ← Human submits or agent generates
                     └────┬────┘
                          │
                     ┌────▼────┐
                     │RESEARCH │ ← Agents investigate feasibility
                     └────┬────┘
                          │
                     ┌────▼────┐
                     │VALIDATE │ ← Scored on multiple dimensions
                     └────┬────┘
                          │
                   ┌──────┴──────┐
                   │             │
              ┌────▼────┐  ┌────▼────┐
              │PROMOTED │  │ARCHIVED │ ← With full reasoning
              └────┬────┘  └─────────┘
                   │
              ┌────▼────┐
              │PLANNING │ ← Agents draft execution plan
              └────┬────┘
                   │
              ┌────▼──────┐
              │ EXECUTING  │ ← Requires human approval for external actions
              └────┬──────┘
                   │
              ┌────▼────┐
              │  DONE   │
              └─────────┘
```

**Tracked via artifact tags:** `idea:new`, `idea:researching`, `idea:validated`, `idea:promoted`, `idea:planning`, `idea:executing`, `idea:done`, `idea:archived`.

### 7.3 Scoring Dimensions

Each idea is scored (0.0 to 1.0) on:

| Dimension | Description |
|-----------|-------------|
| `market_size` | How big is the addressable market? |
| `feasibility` | Can we build/execute this with our current stack and resources? |
| `competitive_advantage` | Do we have a unique angle or moat? |
| `revenue_potential` | Realistic revenue estimate (relative scale) |
| `effort_required` | Inverse of effort — higher = less effort needed |
| `alignment` | How well does this fit our existing products and direction? |
| `time_to_revenue` | How quickly could this generate income? |

**Composite score:** Weighted average. Default weights emphasize feasibility and time_to_revenue (because we need early wins). Weights configurable via persona settings.

---

## 8. Gap Analysis

### 8.1 What's Missing Today

| Gap | Severity | Required For | Notes |
|-----|----------|-------------|-------|
| **No file/artifact storage in Agent-Hub** | Critical | Everything | This is the #1 blocker — the Artifact Hub core |
| **No artifact tools for agents** | Critical | Agent workflows | Agents can't create/search artifacts during completion |
| **No business ops agents** | High | Autonomous ops | 5 new agents need to be defined, prompted, and tuned |
| **No experiment engine abstraction** | Medium | Autoresearch loop | Existing benchmark code is directly callable but not abstracted |
| **No web research capability** | High | Market research, BD | Agents need web search/fetch tools to do real research |
| **No external publishing tools** | Medium | Content/marketing | Agents need tools to draft posts, manage social, etc. (behind escalation) |
| **No donation/sponsorship infrastructure** | Low | Revenue | GitHub Sponsors, Buy Me a Coffee, Patreon — need accounts and integration |
| **No public-facing landing pages** | Medium | Revenue | Need to present the products to potential users/customers |
| **No analytics on business experiment outcomes** | Low | Measurement | Dashboard for tracking idea pipeline health, experiment throughput |

### 8.2 What Already Works (No Gaps)

- Agent orchestration (persona + heartbeat + scheduler + Hatchet)
- Agent dispatch and completion (`complete_internal()`)
- Multi-agent review pipeline (supervisor + critic)
- Benchmark infrastructure (runs, experiments, attempts, regression clusters)
- Memory system (mandates, guardrails, references, tiers)
- Push notifications
- Project-scoped access control
- Shared React component packages
- Docker container architecture (in progress)

### 8.3 Web Research Tools

Agents currently lack the ability to search the web or fetch URLs. This is critical for market research, competitor analysis, and trend monitoring.

**Recommendation:** Add web_search and web_fetch as agent tools:
- `web_search` — uses a search API (SerpAPI, Brave Search, or Tavily) to find relevant pages
- `web_fetch` — fetches and extracts content from a URL (similar to Claude Code's WebFetch)
- Both gated behind project/runtime policy
- Rate-limited to prevent abuse

This is the single most important gap for autonomous business ops. Without web access, "market research" is limited to the agent's training data.

---

## 9. Phased Rollout

### Phase 1: Foundation (Weeks 1-2)
**Goal:** Artifact Hub is operational and accessible from Agent-Hub UI.

- [ ] Create `artifacts`, `artifact_versions`, `artifact_permissions` tables (Alembic migration)
- [ ] Implement `StorageBackend` (local filesystem) and `ArtifactService`
- [ ] Build `/api/artifacts` and `/api/artifact-permissions` routers
- [ ] Implement artifact agent tools (`create_artifact`, `search_artifacts`, `get_artifact`, `update_artifact`)
- [ ] Build `@agent-hub/artifact-panel` package (browser, viewer, drop zone, search)
- [ ] Integrate panel into Agent-Hub frontend
- [ ] Seed default permissions

**Value delivered:** Humans and agents can create, search, and browse artifacts from Agent-Hub.

### Phase 2: Cross-Project Integration (Weeks 3-4)
**Goal:** All projects can access the Artifact Hub.

- [ ] Integrate `@agent-hub/artifact-panel` into SummitFlow frontend
- [ ] Integrate into Portfolio-AI frontend
- [ ] Integrate into A-Term frontend
- [ ] SummitFlow dual-write for new design assets
- [ ] Portfolio-AI dual-write for new document uploads
- [ ] Docker shared volume configuration

**Value delivered:** Unified artifact access across the entire ecosystem.

### Phase 3: Business Ops Agents (Weeks 5-6)
**Goal:** Specialist agents are operational and producing artifacts.

- [ ] Define and seed 5 new business ops agents (market-researcher, business-developer, strategist, content-creator, idea-researcher)
- [ ] Add web_search and web_fetch agent tools
- [ ] Create `business_experiments` and `business_experiment_attempts` tables
- [ ] Implement `BusinessResearchRunner` for the experiment engine
- [ ] Seed scheduled jobs for recurring business ops
- [ ] Implement escalation artifact flow + push notification triggers

**Value delivered:** The persona autonomously runs market research, generates ideas, and stores structured outputs.

### Phase 4: Autoresearch Loop (Weeks 7-8)
**Goal:** The autonomous experiment loop is running and producing validated ideas.

- [ ] Extract shared `ExperimentEngine` from existing benchmark code
- [ ] Implement `AgentBenchmarkRunner` adapter (wraps existing logic)
- [ ] Implement `BusinessResearchRunner` with scoring dimensions
- [ ] Build experiment loop Hatchet workflow (4-hour cadence)
- [ ] Implement idea pipeline lifecycle (new → research → validate → promote/archive)
- [ ] Bidirectional idea flow (human → agents, agents → human)
- [ ] Experiment dashboard in Agent-Hub frontend

**Value delivered:** Autonomous hypothesis generation, research, validation, and structured output.

### Phase 5: Revenue Infrastructure (Weeks 9-10)
**Goal:** Donation/sponsorship channels live; first revenue-generating ideas in execution.

- [ ] Set up GitHub Sponsors / Buy Me a Coffee / Patreon (human task, agents draft content)
- [ ] Agents research and recommend revenue model for each product
- [ ] Landing pages for public-facing products (agents draft, human approves)
- [ ] First promoted idea enters execution phase
- [ ] Content creation pipeline producing marketing materials

**Value delivered:** Revenue channels exist; business ops pipeline is end-to-end operational.

### Phase 6: Migration Completion & Polish (Weeks 11-12)
**Goal:** Legacy storage consolidated; system mature.

- [ ] Backfill existing SummitFlow design assets into Hub
- [ ] Backfill existing Portfolio-AI documents and research artifacts
- [ ] Business ops analytics dashboard
- [ ] Tune agent prompts based on first 4-6 weeks of experiment data
- [ ] Performance optimization (query tuning, caching hot artifacts in Redis)

**Value delivered:** Single source of truth for all artifacts; tuned autonomous ops.

---

## 10. Holistic Integration

### 10.1 How Everything Connects

```
┌─────────────────────────────────────────────────────────────────┐
│                        Artifact Hub                              │
│                   (Agent-Hub module)                              │
│                                                                  │
│   Global artifacts ←→ Project-scoped artifacts                   │
│   Human uploads    ←→ Agent-generated outputs                    │
│   Ideas & research ←→ Experiment results                         │
│                                                                  │
├──────────┬──────────┬──────────┬──────────┬─────────────────────┤
│          │          │          │          │                      │
│ Agent-Hub│SummitFlow│Portfolio │ A-Term   │  Future Projects     │
│          │          │   -AI    │          │                      │
│ Full     │ Design   │ Research │ Upload & │  Import package,     │
│ panel    │ assets,  │ docs,    │ browse   │  pass URL +          │
│          │ mockups, │ analysis,│          │  project context     │
│          │ plans    │ screenshots         │                      │
└──────────┴──────────┴──────────┴──────────┴─────────────────────┘
         │                                           │
         ▼                                           ▼
┌─────────────────────┐                ┌──────────────────────────┐
│  Agent Workflows     │                │  Autonomous Business Ops │
│                      │                │                          │
│  create_artifact     │                │  Persona orchestrates:   │
│  search_artifacts    │                │  ├─ market-researcher    │
│  get_artifact        │                │  ├─ business-developer   │
│  update_artifact     │                │  ├─ strategist           │
│                      │                │  ├─ content-creator      │
│  All 36+ agents can  │                │  ├─ idea-researcher      │
│  read/write artifacts│                │  └─ critic (review)      │
│  during completion   │                │                          │
└──────────┬───────────┘                │  Experiment Loop:        │
           │                            │  Hypothesize → Research  │
           ▼                            │  → Validate → Decide     │
┌─────────────────────┐                │  → Store → Repeat        │
│  Experiment Engine   │                │                          │
│  (shared logic)      │◄───────────────┤  Idea Pipeline:          │
│                      │                │  Human ↔ Agent flow      │
│  AgentBenchmarkRunner│                │  with structured         │
│  BusinessResearchRunner               │  critique & refinement   │
│                      │                └──────────────────────────┘
│  Same loop:          │
│  Iterate → Score     │
│  → Keep/Discard      │
│  → Log → Repeat      │
└──────────────────────┘
```

### 10.2 Benefits Per Project

**Agent-Hub:**
- Becomes the canonical storage layer for all ecosystem artifacts
- Agents gain persistent shared workspace (not just ephemeral chat)
- Experiment engine unifies agent benchmarking and business research
- Business ops dashboard adds a new dimension to the monitoring UI

**SummitFlow:**
- Design assets accessible from any project (not siloed)
- Plans and specs stored as versioned artifacts with full-text search
- Business ops agents can research design trends, competitor UIs, pricing for design tools

**Portfolio-AI:**
- Research artifacts consolidated with everything else
- Investment research feeds into business strategy (equity-analyst outputs are artifacts)
- Household documents have a backup canonical location

**A-Term:**
- File uploads can persist beyond sessions via the Hub
- Browse any artifact from the A-Term UI
- Agents running in A-Term sessions can store outputs

### 10.3 What We Might Be Missing

1. **Notification preferences** — users should be able to configure which escalations/updates trigger push notifications vs. just appear in the artifact feed. Low priority but worth noting.

2. **Artifact comments/discussion** — the current design has artifacts and versions but no inline discussion thread. Could be useful for human ↔ agent dialogue on a specific artifact. Consider adding later if needed (simple `artifact_comments` table).

3. **Artifact templates** — for recurring artifact types (weekly market report, idea submission, experiment log), pre-defined templates could improve consistency. Not critical for v1.

4. **Rate limiting for agent artifact creation** — if experiment loops run aggressively, they could create thousands of artifacts. Add a configurable daily artifact budget per agent (similar to `daily_token_budget`).

5. **Artifact expiry/retention** — some artifacts (intermediate research, failed experiments) may not need permanent storage. Consider a TTL or auto-archive policy for certain artifact types.

6. **Cross-project artifact linking** — an artifact in SummitFlow might reference research from Portfolio-AI. The `parent_id` handles parent-child but not arbitrary cross-references. The `metadata` JSONB field can handle this for now; a proper `artifact_links` junction table could come later.
