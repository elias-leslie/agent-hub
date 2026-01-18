# Memory Dashboard Task Prompt

## Context

Agent Hub uses Graphiti (Neo4j-based knowledge graph) for memory storage. The memory system works - episodes can be added, searched, and injected into chat completions. However, there is NO frontend to visualize or manage stored memories.

## Current State

- **Backend endpoints exist:**
  - `POST /api/memory/add` - Add episodes
  - `GET /api/memory/search` - Search by query
  - `GET /api/memory/context` - Get formatted context for injection
  - `DELETE /api/memory/episode/{id}` - Not implemented yet

- **No frontend:** Zero UI for memory management

- **Neo4j Browser available** at localhost:7474 but requires Cypher knowledge

## Task

Create a Memory Dashboard page at `/memory` in agent-hub frontend that allows users to:

1. **Browse memories** - View all stored episodes/facts with pagination
2. **Search** - Query interface to find specific memories
3. **Filter by group** - Memory is isolated by group_id (project, user, etc.)
4. **View details** - Expand episode to see extracted entities, relationships, facts
5. **Delete** - Remove outdated or incorrect memories
6. **Visualize** - Optional: graph visualization of entity relationships

## Technical Notes

- Frontend: Next.js 14 (app router), Tailwind, shadcn/ui components
- Backend: FastAPI at localhost:8003
- Memory service: `backend/app/services/memory/service.py`
- Graphiti client: `backend/app/services/memory/graphiti_client.py`

## Design Direction

Match existing agent-hub dark theme aesthetic (see `/chat`, `/dashboard` pages). Use existing UI patterns from the codebase.

## Questions to Explore in Planning

- Should there be bulk operations (delete all in group, export)?
- How to handle large memory stores (virtual scrolling, pagination)?
- Should memories be editable or just deletable?
- Entity graph visualization - worth the complexity?
- Integration with chat - "forget this" command from chat?
