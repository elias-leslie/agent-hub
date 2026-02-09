"""Agent memory tools for recording learnings during execution.

These tools allow agents to capture discoveries, gotchas, and patterns
during task execution for cross-session knowledge transfer.
"""

import logging

from graphiti_core.utils.datetime_utils import utc_now

from .episode_creator import get_episode_creator
from .episode_creator_models import CreateResult
from .ingestion_config import LEARNING, TOOL_DISCOVERY, TOOL_GOTCHA
from .service import MemoryScope, MemorySource, get_memory_service
from .tools_schemas import (
    RecordDiscoveryRequest,
    RecordGotchaRequest,
    RecordPatternRequest,
    RecordResponse,
    SessionContextResponse,
)

logger = logging.getLogger(__name__)


def _build_response(result: CreateResult, success_msg: str, log_prefix: str) -> RecordResponse:
    """Build RecordResponse from CreateResult."""
    if result.success:
        logger.info("%s (uuid: %s)", log_prefix, result.uuid)
        return RecordResponse(success=True, episode_uuid=result.uuid or "", message=success_msg)
    logger.error("Failed to record: %s", result.validation_error)
    return RecordResponse(
        success=False, episode_uuid="", message=f"Failed: {result.validation_error}"
    )


async def record_discovery(request: RecordDiscoveryRequest) -> RecordResponse:
    """Record a codebase discovery for future reference."""
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)
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

    return _build_response(
        result,
        f"Discovery recorded: {request.file_path}",
        f"Recorded discovery: {request.description[:50]} in {request.file_path}",
    )


async def record_gotcha(request: RecordGotchaRequest) -> RecordResponse:
    """Record a gotcha/pitfall for future troubleshooting."""
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)
    content_parts = [f"Gotcha: {request.gotcha}", f"Context: {request.context}"]
    if request.solution:
        content_parts.append(f"Solution: {request.solution}")

    result = await creator.create(
        content="\n".join(content_parts),
        name=f"gotcha_{utc_now().strftime('%Y%m%d_%H%M%S')}",
        config=TOOL_GOTCHA,
        source_description="troubleshooting gotcha pitfall",
        reference_time=utc_now(),
        source=MemorySource.SYSTEM,
    )

    return _build_response(
        result,
        f"Gotcha recorded: {request.gotcha[:50]}...",
        f"Recorded gotcha: {request.gotcha[:50]}",
    )


async def record_pattern(request: RecordPatternRequest) -> RecordResponse:
    """Record a coding pattern for future reference."""
    creator = get_episode_creator(scope=request.scope, scope_id=request.scope_id)
    content_parts = [f"Pattern: {request.pattern}", f"Applies to: {request.applies_to}"]
    if request.example:
        content_parts.append(f"Example: {request.example}")

    result = await creator.create(
        content="\n".join(content_parts),
        name=f"pattern_{utc_now().strftime('%Y%m%d_%H%M%S')}",
        config=LEARNING,
        source_description="coding standard pattern best practice",
        reference_time=utc_now(),
        source=MemorySource.SYSTEM,
    )

    return _build_response(
        result,
        f"Pattern recorded: {request.pattern[:50]}...",
        f"Recorded pattern: {request.pattern[:50]}",
    )


async def get_session_context(
    scope: MemoryScope = MemoryScope.PROJECT,
    scope_id: str | None = None,
    num_results: int = 10,
) -> SessionContextResponse:
    """Get accumulated learnings from previous sessions.

    Retrieves discoveries, gotchas, and patterns that may be relevant
    for the current session.
    """
    service = get_memory_service(scope=scope, scope_id=scope_id)

    try:
        # Get patterns and gotchas using the dedicated method
        patterns, gotchas = await service.get_patterns_and_gotchas(
            query="coding patterns and practices",
            num_results=num_results,
            min_score=0.3,
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
