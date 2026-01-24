"""Agent memory tools for recording learnings during execution.

These tools allow agents to capture discoveries, gotchas, and patterns
during task execution for cross-session knowledge transfer.
"""

import logging

from graphiti_core.utils.datetime_utils import utc_now
from pydantic import BaseModel, Field

from .episode_creator import get_episode_creator
from .ingestion_config import LEARNING, TOOL_DISCOVERY, TOOL_GOTCHA
from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
    get_memory_service,
)

logger = logging.getLogger(__name__)


class RecordDiscoveryRequest(BaseModel):
    """Request to record a codebase discovery."""

    file_path: str = Field(..., description="File path where discovery was made")
    description: str = Field(..., description="Description of the discovery")
    category: MemoryCategory = Field(
        default=MemoryCategory.DOMAIN_KNOWLEDGE,
        description="Category of the discovery",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this discovery",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordGotchaRequest(BaseModel):
    """Request to record a gotcha/pitfall."""

    gotcha: str = Field(..., description="The gotcha or pitfall encountered")
    context: str = Field(..., description="Context in which the gotcha was found")
    solution: str | None = Field(
        default=None,
        description="Solution or workaround if known",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this gotcha",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordPatternRequest(BaseModel):
    """Request to record a coding pattern."""

    pattern: str = Field(..., description="Description of the pattern")
    applies_to: str = Field(..., description="Where/when this pattern applies")
    example: str | None = Field(
        default=None,
        description="Example of the pattern in use",
    )
    scope: MemoryScope = Field(
        default=MemoryScope.PROJECT,
        description="Scope for this pattern",
    )
    scope_id: str | None = Field(
        default=None,
        description="Project or task ID for scoping",
    )


class RecordResponse(BaseModel):
    """Response from a record operation."""

    success: bool
    episode_uuid: str
    message: str


class SessionContextResponse(BaseModel):
    """Response containing accumulated session context."""

    discoveries: list[MemorySearchResult] = []
    gotchas: list[MemorySearchResult] = []
    patterns: list[MemorySearchResult] = []
    session_count: int = 0


async def record_discovery(request: RecordDiscoveryRequest) -> RecordResponse:
    """
    Record a codebase discovery for future reference.

    Args:
        request: Discovery details including file path and description

    Returns:
        RecordResponse with success status and episode UUID
    """
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)

    # Build content for the episode
    content = f"Discovery in {request.file_path}: {request.description}"
    name = f"discovery_{request.file_path.replace('/', '_').replace('.', '_')}"
    source_description = f"codebase discovery {request.category.value}"

    result = await creator.create(
        content=content,
        name=name,
        config=TOOL_DISCOVERY,
        source_description=source_description,
        reference_time=utc_now(),
        source=MemorySource.SYSTEM,
    )

    if result.success:
        logger.info(
            "Recorded discovery: %s in %s (scope: %s)",
            request.description[:50],
            request.file_path,
            request.scope.value,
        )
        return RecordResponse(
            success=True,
            episode_uuid=result.uuid or "",
            message=f"Discovery recorded: {request.file_path}",
        )
    else:
        logger.error("Failed to record discovery: %s", result.validation_error)
        return RecordResponse(
            success=False,
            episode_uuid="",
            message=f"Failed to record discovery: {result.validation_error}",
        )


async def record_gotcha(request: RecordGotchaRequest) -> RecordResponse:
    """
    Record a gotcha/pitfall for future troubleshooting.

    Args:
        request: Gotcha details including context and optional solution

    Returns:
        RecordResponse with success status and episode UUID
    """
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)

    # Build content for the episode
    content_parts = [
        f"Gotcha: {request.gotcha}",
        f"Context: {request.context}",
    ]
    if request.solution:
        content_parts.append(f"Solution: {request.solution}")

    content = "\n".join(content_parts)
    name = f"gotcha_{utc_now().strftime('%Y%m%d_%H%M%S')}"
    source_description = "troubleshooting gotcha pitfall"

    result = await creator.create(
        content=content,
        name=name,
        config=TOOL_GOTCHA,
        source_description=source_description,
        reference_time=utc_now(),
        source=MemorySource.SYSTEM,
    )

    if result.success:
        logger.info(
            "Recorded gotcha: %s (scope: %s)",
            request.gotcha[:50],
            request.scope.value,
        )
        return RecordResponse(
            success=True,
            episode_uuid=result.uuid or "",
            message=f"Gotcha recorded: {request.gotcha[:50]}...",
        )
    else:
        logger.error("Failed to record gotcha: %s", result.validation_error)
        return RecordResponse(
            success=False,
            episode_uuid="",
            message=f"Failed to record gotcha: {result.validation_error}",
        )


async def record_pattern(request: RecordPatternRequest) -> RecordResponse:
    """
    Record a coding pattern for future reference.

    Args:
        request: Pattern details including where it applies

    Returns:
        RecordResponse with success status and episode UUID
    """
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)

    # Build content for the episode
    content_parts = [
        f"Pattern: {request.pattern}",
        f"Applies to: {request.applies_to}",
    ]
    if request.example:
        content_parts.append(f"Example: {request.example}")

    content = "\n".join(content_parts)
    name = f"pattern_{utc_now().strftime('%Y%m%d_%H%M%S')}"
    source_description = "coding standard pattern best practice"

    result = await creator.create(
        content=content,
        name=name,
        config=LEARNING,
        source_description=source_description,
        reference_time=utc_now(),
        source=MemorySource.SYSTEM,
    )

    if result.success:
        logger.info(
            "Recorded pattern: %s (scope: %s)",
            request.pattern[:50],
            request.scope.value,
        )
        return RecordResponse(
            success=True,
            episode_uuid=result.uuid or "",
            message=f"Pattern recorded: {request.pattern[:50]}...",
        )
    else:
        logger.error("Failed to record pattern: %s", result.validation_error)
        return RecordResponse(
            success=False,
            episode_uuid="",
            message=f"Failed to record pattern: {result.validation_error}",
        )


async def get_session_context(
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    num_results: int = 10,
) -> SessionContextResponse:
    """
    Get accumulated learnings from previous sessions.

    Retrieves discoveries, gotchas, and patterns that may be relevant
    for the current session.

    Args:
        scope: Memory scope to query
        scope_id: Project or task ID
        num_results: Maximum results per category

    Returns:
        SessionContextResponse with categorized learnings
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    try:
        # Get patterns and gotchas using the dedicated method
        patterns, gotchas = await service.get_patterns_and_gotchas(
            query="coding patterns and practices",
            num_results=num_results,
            min_score=0.3,  # Lower threshold for session context
        )

        # Search for discoveries
        discovery_results = await service.search(
            query="codebase discovery",
            limit=num_results,
            min_score=0.3,
        )

        return SessionContextResponse(
            discoveries=discovery_results,
            gotchas=gotchas,
            patterns=patterns,
            session_count=len(discovery_results) + len(gotchas) + len(patterns),
        )
    except Exception as e:
        logger.error("Failed to get session context: %s", e)
        return SessionContextResponse()


def format_session_context_for_injection(context: SessionContextResponse) -> str:
    """
    Format session context as a string for system prompt injection.

    Args:
        context: SessionContextResponse with categorized learnings

    Returns:
        Formatted string suitable for injection into prompts
    """
    if context.session_count == 0:
        return ""

    parts = []

    if context.patterns:
        parts.append("## Relevant Patterns")
        for p in context.patterns:
            parts.append(f"- {p.content}")

    if context.gotchas:
        parts.append("\n## Known Gotchas")
        for g in context.gotchas:
            parts.append(f"- {g.content}")

    if context.discoveries:
        parts.append("\n## Recent Discoveries")
        for d in context.discoveries[:5]:  # Limit discoveries
            parts.append(f"- {d.content}")

    return "\n".join(parts)
