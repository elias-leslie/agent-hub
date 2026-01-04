# Agent Hub Specification

**Status:** Complete | **Last Updated:** 2026-01-03

---

## Overview

Agent Hub is a unified agentic AI service that consolidates scattered Claude/Gemini implementations across summitflow and portfolio-ai into a single, project-agnostic service. It provides centralized credential management, automatic model fallback, and full observability via REST + WebSocket APIs and a management UI.

---

## Current State

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CURRENT (Fragmented)                          │
├─────────────────────────────────────────────────────────────────────┤
│  summitflow                       │  portfolio-ai                    │
│  ├── services/agents/claude.py    │  ├── agents/clients/claude.py   │
│  ├── services/agents/gemini.py    │  ├── agents/clients/gemini.py   │
│  ├── services/roundtable/         │  └── services/dev-companion/    │
│  └── services/implementation_*    │                                  │
├─────────────────────────────────────────────────────────────────────┤
│  Problems:                                                           │
│  • 30+ hardcoded paths (/home/kasadis/summitflow)                   │
│  • Project-specific logic scattered throughout                       │
│  • No retry/backoff logic - single failure = exception              │
│  • Credential management is ad-hoc                                   │
│  • Class-level mutable state causing potential race conditions       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Desired State

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AGENT HUB                                   │
│                      (standalone service)                            │
├─────────────────────────────────────────────────────────────────────┤
│  REST API (/complete, /stream, /sessions, /status)                  │
│  WebSocket API (real-time streaming, roundtable)                    │
├─────────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │Model Router │  │  Provider   │  │ Credential  │                 │
│  │ + Fallback  │──│  Adapters   │──│   Store     │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘                 │
│         │               │                │                          │
│         ▼               ▼                ▼                          │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐                 │
│  │   Claude    │  │   Gemini    │  │ PostgreSQL  │                 │
│  │   (SDK)     │  │   (ADK)     │  │ (encrypted) │                 │
│  └─────────────┘  └─────────────┘  └─────────────┘                 │
├─────────────────────────────────────────────────────────────────────┤
│  Management UI (standalone web app)                                  │
│  • Dashboard: sessions, costs, errors, metrics                      │
│  • Interactive Chat: single agent + roundtable mode                 │
│  • Settings: credential CRUD, fallback rules                        │
└─────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Consumers (call Agent Hub API)                                      │
│  • SummitFlow (autonomous execution, code health agent)             │
│  • portfolio-ai (dev-companion, stock analysis)                     │
│  • Future projects                                                   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Key Gaps (Critical to Fix)

| Gap | Severity | Impact |
|-----|----------|--------|
| 30+ hardcoded paths in existing code | Critical | Not portable, breaks on different machines |
| Project-specific logic scattered | Critical | Can't be used by other projects |
| No retry/backoff logic | High | Single transient failure = complete failure |
| Ad-hoc credential management | High | Security risk, hard to audit |
| Class-level mutable state | Medium | Race conditions in concurrent usage |

---

## Key Decisions

| Decision | Rationale |
|----------|-----------|
| Standalone service with own database | Maximizes portability, clean boundaries |
| PostgreSQL credential storage | Centralized, auditable, matches portfolio-ai pattern |
| Native SDK tool calling | Most robust, proper permissions, SDK handles edge cases |
| Big bang migration | Projects not fully production yet, clean cut faster |
| REST + WebSocket APIs | REST for automation, WebSocket for interactive |
| frontend-design plugin for UI | User requirement for high design quality |

---

## Components

### Backend (agent-hub-core)

| Capability | Priority | Description |
|------------|----------|-------------|
| Completion API | P0 | REST `/complete` endpoint |
| Streaming API | P0 | WebSocket real-time streaming |
| Session Management | P0 | CRUD + persistence across restarts |
| Model Router | P0 | Tier selection, fallback chains |
| Provider Adapters | P0 | Claude SDK, Gemini ADK |
| Credential Store | P0 | Encrypted PostgreSQL storage |
| Tool Execution | P0 | Native SDK hooks, permissions |
| Cost Tracking | P1 | Per-request logging, aggregation |
| Event Publishing | P1 | WebSocket events, webhooks |
| Observability | P1 | /health, /metrics, /status |

### Frontend (agent-hub-ui)

| Capability | Priority | Description |
|------------|----------|-------------|
| Dashboard | P0 | Sessions, costs, errors, metrics |
| Interactive Chat | P0 | Single + roundtable mode |
| Settings Page | P0 | Credential CRUD, fallback rules |
| Session Viewer | P1 | History, messages, tool calls |

---

## Implementation Phases

```
Phase 1: Core Infrastructure
├── PostgreSQL schema
├── Claude adapter
├── Gemini adapter
├── /complete endpoint
└── Basic fallback

Phase 2: Session & Streaming
├── Session CRUD
├── WebSocket streaming
└── SDK session resumption

Phase 3: Tool Support
├── Claude PreToolUse hooks
├── Gemini callbacks
└── Permission model (YOLO + granular)

Phase 4: Credential Management
├── Encrypted storage
└── CRUD API

Phase 5: Observability
├── Health/metrics/status
└── Cost logging

Phase 6: Event Publishing
├── WebSocket events
└── Webhook callbacks

Phase 7: UI Development
├── Dashboard
├── Interactive Chat
└── Settings

Phase 8: Migration
├── Switch consumers
└── Delete old code
```

---

## Patterns to Absorb

| Pattern | Source | Adaptation |
|---------|--------|------------|
| DualProviderClient | agents/__init__.py | Configurable fallback chains |
| Tier-based selection | tier_classifier.py | Configurable tier→model mapping |
| Thrashing detection | implementation_executor.py | Error signature hashing in router |
| Permission hooks | claude.py, gemini.py | Centralized tool execution layer |
| Credential storage | credential_loader.py | Add encryption, expand for OAuth |

---

## Success Criteria

1. New projects can use AI by calling Agent Hub API
2. No duplicate Claude/Gemini client code in projects
3. OAuth/credentials managed in one place
4. Both interactive and autonomous workloads supported
5. `grep -r 'summitflow|portfolio-ai' agent-hub/src/` returns nothing
6. `grep -r '/home/' agent-hub/src/` returns nothing

---

## Next Steps

1. **Run `/tdd_it agent-hub`** - Create TDD structure from this spec
2. **Create repository structure** - Standalone codebase
3. **Invoke frontend-design plugin** - UI/UX decisions
4. **Run `/spec_it` on memory-system** - Next integration target
