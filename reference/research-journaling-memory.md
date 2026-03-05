# Research: How OpenClaw and Auto-Claude Handle Journaling/Memory

## Context from Prior Session

We discovered that Jenny's (persona agent) system prompt was **107KB** — with **88% (90KB)** consumed by journal entries. The root cause was `_fetch_journal_memories()` in `backend/app/services/_persona_context.py` which had `limit=100`, dumping up to 100 journal entries into the system prompt unconditionally.

This caused an `[Errno 7] Argument list too long` crash because the Claude Agent SDK passes the system prompt as a `--system-prompt` CLI argument, and ~109KB approached the 128KB MAX_ARG_STRLEN kernel limit.

### Fix Applied (commit b8bbdc5)
- Reduced journal limit from 100 to 10 entries
- Added 8KB character budget with oldest-first dropping
- System prompt expected to drop from ~107KB to ~20KB

### Open Questions
The fix is a band-aid cap. The deeper questions are:
1. How should journal entries be managed over time? (summarization? tiered retention? relevance scoring?)
2. Should journals be in the system prompt at all, or injected differently?
3. How do other agentic systems handle persistent memory/journaling for autonomous agents?
4. What's the right balance between context richness and token efficiency?

## Research Task

Explore these two reference codebases and report on their memory/journaling architecture:

### 1. `/home/kasadis/references/openclaw`
- How does it handle agent memory persistence?
- Does it have a journaling system? If so, how are entries stored, retrieved, and pruned?
- How is memory injected into prompts? (system message? user message? separate context?)
- Are there size limits, budgets, or summarization mechanisms?
- How does it handle memory relevance/decay over time?
- Look at: AGENTS.md, CLAUDE.md, any memory/context/journal related code

### 2. `/home/kasadis/references/Auto-Claude`
- Same questions as above
- How does it maintain continuity across sessions?
- Does it distinguish between types of memory (episodic, semantic, procedural)?
- How does it decide what to remember vs forget?

### Deliverable

For each system, document:
1. **Architecture**: How memory/journals are stored (DB? files? in-memory?)
2. **Injection**: How and where memory enters the prompt
3. **Budget/Limits**: Any caps on memory size in prompts
4. **Maintenance**: How old/irrelevant memories are handled (pruning, summarization, decay)
5. **Relevance**: How the system decides which memories matter for a given context

Then provide **recommendations** for Agent Hub's journal injection system, referencing specific patterns from these codebases that we should adopt or adapt.

### Current Agent Hub Architecture (for comparison)
- Journals stored as memory records (`memory_type="journal"`, `scope="agent:persona"`) in PostgreSQL
- `_persona_context.py:_fetch_journal_memories()` fetches by date range + limit
- `_format_journal_section()` renders as `<recent_journal>` XML block in system prompt
- Progressive memory injection (mandates/guardrails/references) is a SEPARATE system with relevance scoring
- Jenny has `mark_memory_relevant`/`mark_memory_irrelevant` tools but these don't affect journal injection
- Key file: `backend/app/services/_persona_context.py`
- Memory system: `backend/app/services/memory/`
