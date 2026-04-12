"""Memory agent tools endpoints - for recording learnings during task execution."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from app.services.memory.learning_extractor import (
    ExtractionResult,
    ExtractLearningsRequest,
    extract_learnings,
)
from app.services.memory.promotion import (
    PromoteRequest,
    PromotionResult,
    get_canonical_context,
    promote_learning,
)
from app.services.memory.service import MemoryScope
from app.services.memory.tools import (
    get_session_context,
    record_discovery,
    record_gotcha,
    record_pattern,
)
from app.services.memory.tools_schemas import (
    RecordDiscoveryRequest,
    RecordGotchaRequest,
    RecordPatternRequest,
    RecordResponse,
    SessionContextResponse,
)

from .memory_agent_handlers import (
    build_progressive_context_response,
    handle_save_learning,
)
from .memory_agent_schemas import (
    CanonicalContextRequest,
    CanonicalContextResponse,
    ProgressiveContextResponse,
    SaveLearningRequest,
    SaveLearningResponse,
)
from .memory_dependencies import get_scope_params

logger = logging.getLogger(__name__)

router = APIRouter()



@router.post("/record-discovery", response_model=RecordResponse)
async def api_record_discovery(request: RecordDiscoveryRequest) -> RecordResponse:
    """Record a codebase discovery for future reference."""
    try:
        return await record_discovery(request)
    except Exception as e:
        logger.exception("Failed to record discovery")
        raise HTTPException(status_code=500, detail=f"Failed to record discovery: {e}") from e


@router.post("/record-gotcha", response_model=RecordResponse)
async def api_record_gotcha(request: RecordGotchaRequest) -> RecordResponse:
    """Record a gotcha/pitfall for troubleshooting."""
    try:
        return await record_gotcha(request)
    except Exception as e:
        logger.exception("Failed to record gotcha")
        raise HTTPException(status_code=500, detail=f"Failed to record gotcha: {e}") from e


@router.post("/record-pattern", response_model=RecordResponse)
async def api_record_pattern(request: RecordPatternRequest) -> RecordResponse:
    """Record a coding pattern for future reference."""
    try:
        return await record_pattern(request)
    except Exception as e:
        logger.exception("Failed to record pattern")
        raise HTTPException(status_code=500, detail=f"Failed to record pattern: {e}") from e


@router.get("/session-context", response_model=SessionContextResponse)
async def api_get_session_context(
    scope: Annotated[MemoryScope, Query(description="Memory scope")] = MemoryScope.PROJECT,
    scope_id: Annotated[str | None, Query(description="Project or task ID")] = None,
    num_results: Annotated[int, Query(ge=1, le=50, description="Max results per category")] = 10,
) -> SessionContextResponse:
    """Get accumulated learnings from previous sessions."""
    try:
        return await get_session_context(scope=scope, scope_id=scope_id, num_results=num_results)
    except Exception as e:
        logger.exception("Failed to get session context")
        raise HTTPException(status_code=500, detail=f"Failed to get session context: {e}") from e


@router.post("/extract-learnings", response_model=ExtractionResult)
async def api_extract_learnings(request: ExtractLearningsRequest) -> ExtractionResult:
    """
    Extract learnings from a Claude Code session transcript.

    Uses LLM analysis to identify verified, inference, and pattern learnings.
    Learnings are stored with status based on confidence (70-89% provisional, 90+ canonical).
    """
    try:
        return await extract_learnings(request)
    except Exception as e:
        logger.exception("Failed to extract learnings")
        raise HTTPException(status_code=500, detail=f"Failed to extract learnings: {e}") from e


@router.post("/promote", response_model=PromotionResult)
async def api_promote_learning(request: PromoteRequest) -> PromotionResult:
    """Manually promote a learning from provisional to canonical status."""
    try:
        return await promote_learning(request)
    except Exception as e:
        logger.exception("Failed to promote learning")
        raise HTTPException(status_code=500, detail=f"Failed to promote learning: {e}") from e


@router.get("/progressive-context", response_model=ProgressiveContextResponse)
async def get_progressive_context(
    query: Annotated[str, Query(..., description="Query to find relevant context")],
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
    debug: Annotated[bool, Query(description="Include debug info")] = False,
    include_global: Annotated[
        bool,
        Query(description="Include global scope when querying project scope (default True)"),
    ] = True,
    variant: Annotated[
        str | None,
        Query(description="A/B variant override (BASELINE, ENHANCED, MINIMAL, AGGRESSIVE)"),
    ] = None,
    external_id: Annotated[
        str | None,
        Query(description="External ID for deterministic variant assignment and metrics correlation"),
    ] = None,
    project_id: Annotated[
        str | None,
        Query(description="Project ID for deterministic variant assignment"),
    ] = None,
    session_id: Annotated[
        str | None,
        Query(description="Session ID for metrics tracking and task outcome correlation"),
    ] = None,
    task_type: Annotated[
        str | None,
        Query(
            description="Task type to trigger type-specific references (e.g., 'database', 'frontend')"
        ),
    ] = None,
    phase: Annotated[
        str | None,
        Query(
            description="Subtask phase to trigger phase-specific references (e.g., 'planning', 'implementation')"
        ),
    ] = None,
    current_branch: Annotated[
        str | None,
        Query(
            description="Current git branch for session continuity scoping (e.g., 'main', 'feature/auth')"
        ),
    ] = None,
    consumer_profile: Annotated[
        str | None,
        Query(
            description=(
                "Caller profile for path-specific rendering "
                "(agent_general, agent_visual, agent_coding, agent_operator, "
                "agent_promptops, agent_runtime, agent_preview, "
                "claude_session_start, codex_startup)"
            )
        ),
    ] = None,
) -> ProgressiveContextResponse:
    """
    Get 3-block progressive disclosure context for a query.

    Returns context in three blocks:
    - Mandates: Golden standards (confidence=100) - always injected
    - Guardrails: Anti-patterns and gotchas (TROUBLESHOOTING_GUIDE)
    - Reference: Patterns and workflows, including type-triggered references

    Designed for SessionStart hooks with minimal token usage (~150-200 tokens).
    """
    scope, scope_id = scope_params

    return await build_progressive_context_response(
        query=query,
        scope=scope,
        scope_id=scope_id,
        debug=debug,
        include_global=include_global,
        task_type=task_type,
        phase=phase,
        variant_override=variant,
        external_id=external_id,
        project_id=project_id,
        session_id=session_id,
        current_branch=current_branch,
        consumer_profile=consumer_profile,
    )


@router.post("/canonical-context", response_model=CanonicalContextResponse)
async def api_get_canonical_context(request: CanonicalContextRequest) -> CanonicalContextResponse:
    """
    Get context from canonical learnings (trusted knowledge).

    By default only returns canonical (90+ confidence) learnings.
    Set include_provisional=true to also include provisional learnings.
    """
    try:
        facts = await get_canonical_context(
            query=request.query,
            max_facts=request.max_facts,
            include_provisional=request.include_provisional,
        )
        return CanonicalContextResponse(facts=facts, count=len(facts))
    except Exception as e:
        logger.exception("Failed to get canonical context")
        raise HTTPException(status_code=500, detail=f"Failed to get canonical context: {e}") from e


@router.post("/save-learning", response_model=SaveLearningResponse)
async def api_save_learning(
    request: SaveLearningRequest,
    scope_params: Annotated[tuple[MemoryScope, str | None], Depends(get_scope_params)],
) -> SaveLearningResponse:
    """
    Save a learning from a Claude Code session.

    Allows Claude to save learnings discovered during a session.
    Learnings are stored with the provided confidence level and categorized
    as provisional (70-89%) or canonical (90+%).

    Duplicate detection: If a semantically similar learning exists, the existing
    learning is reinforced instead of creating a duplicate.

    **Claude can call this via curl:**
    ```bash
    curl -X POST http://localhost:8003/api/memory/save-learning \\
      -H "Content-Type: application/json" \\
      -d '{"content": "**Async DB**: Use async methods for DB operations.", "injection_tier": "reference"}'
    ```
    """
    from app.services.memory.episode_validation import EpisodeValidationError

    scope, scope_id = scope_params

    try:
        return await handle_save_learning(request, scope, scope_id)
    except EpisodeValidationError as e:
        raise HTTPException(
            status_code=422,
            detail={
                "error": "validation_error",
                "message": e.message,
                "details": [{"message": pattern} for pattern in e.detected_patterns],
                "hint": """FORMAT_STANDARD for memory episodes:

| # | Rule | Check |
|---|------|-------|
| 1 | Topic header | Must start with a bold topic header like **Git Safety**: |
| 2 | Imperative mood | Commands not suggestions |
| 3 | Strong verb first | Lead with use / never / always / check / follow |
| 4 | One atomic rule | Single concept per episode, not a list |
| 5 | No custom delimiters | No ::, -> except in tables |
| 6 | No conversational | No please/remember/note:/you should |
| 7 | Terse content | Prefer 3 sentences max and 280 chars max |
| 8 | Summary | 10-40 chars |

Example of GOOD format:
  **Git Publish**: Use commit.sh --push --msg "description" for new commits. Use commit.sh --current --push for clean ahead branches. Why: both stay on the canonical publish path.

Example of BAD format:
  When working with git, you should remember to always commit first.
  Please don't use git stash because it might cause lost work.""",
            },
        ) from e
    except Exception as e:
        logger.exception("Failed to save learning")
        raise HTTPException(status_code=500, detail=f"Failed to save learning: {e}") from e
