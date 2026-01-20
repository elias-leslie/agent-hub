"""
Memory consolidation service for task completion.

Handles:
- Promoting successful task memories to project scope
- Cleaning up failed task memories (noise reduction)
- Crystallizing patterns from task outcomes
"""

import logging
from datetime import UTC, datetime

from pydantic import BaseModel, Field

from .service import (
    MemoryCategory,
    MemoryScope,
    MemorySource,
    get_memory_service,
)

logger = logging.getLogger(__name__)


class ConsolidationResult(BaseModel):
    """Result of memory consolidation operation."""

    task_id: str
    success: bool
    promoted_count: int = 0
    deleted_count: int = 0
    crystallized_count: int = 0
    message: str


class ConsolidationRequest(BaseModel):
    """Request to consolidate task memories."""

    task_id: str = Field(..., description="ID of the task to consolidate")
    success: bool = Field(..., description="Whether the task completed successfully")
    project_id: str | None = Field(
        default=None,
        description="Project ID for promotion (required for success case)",
    )
    task_summary: str | None = Field(
        default=None,
        description="Summary of task outcome for crystallization",
    )


async def consolidate_task_memories(request: ConsolidationRequest) -> ConsolidationResult:
    """
    Consolidate memories after task completion.

    On success:
    - Promote valuable TASK-scoped memories to PROJECT scope
    - Crystallize patterns from task outcomes

    On failure:
    - Delete ephemeral TASK memories to reduce noise
    - Keep only gotchas/troubleshooting for future reference

    Args:
        request: Consolidation request with task ID and outcome

    Returns:
        ConsolidationResult with counts of processed memories
    """
    task_service = get_memory_service(scope=MemoryScope.TASK, scope_id=request.task_id)

    if request.success:
        return await _consolidate_success(
            task_service=task_service,
            task_id=request.task_id,
            project_id=request.project_id,
            task_summary=request.task_summary,
        )
    else:
        return await _consolidate_failure(
            task_service=task_service,
            task_id=request.task_id,
        )


async def _consolidate_success(
    task_service,
    task_id: str,
    project_id: str | None,
    task_summary: str | None,
) -> ConsolidationResult:
    """Handle consolidation for successful task completion."""
    promoted_count = 0
    crystallized_count = 0

    # Get all episodes from the task scope
    try:
        episodes = await task_service.list_episodes(limit=100)
    except Exception as e:
        logger.error("Failed to list task episodes: %s", e)
        return ConsolidationResult(
            task_id=task_id,
            success=False,
            message=f"Failed to list episodes: {e}",
        )

    # Categories to promote to project scope
    promotable_categories = {
        MemoryCategory.CODING_STANDARD,
        MemoryCategory.TROUBLESHOOTING_GUIDE,
        MemoryCategory.SYSTEM_DESIGN,
        MemoryCategory.DOMAIN_KNOWLEDGE,
    }

    # Get project service for promotion
    effective_project_id = project_id or "default"
    project_service = get_memory_service(
        scope=MemoryScope.PROJECT,
        scope_id=effective_project_id,
    )

    for episode in episodes.episodes:
        if episode.category in promotable_categories:
            # Re-add the episode at project scope
            try:
                await project_service.add_episode(
                    content=episode.content,
                    source=episode.source,
                    source_description=f"promoted from task:{task_id} - {episode.source_description}",
                    reference_time=datetime.now(UTC),
                )
                promoted_count += 1
                logger.debug("Promoted episode %s to project scope", episode.uuid)
            except Exception as e:
                logger.warning("Failed to promote episode %s: %s", episode.uuid, e)

    # Crystallize patterns from task summary
    if task_summary and promoted_count > 0:
        try:
            await project_service.add_episode(
                content=f"Task outcome: {task_summary}",
                source=MemorySource.SYSTEM,
                source_description="task outcome crystallization",
                reference_time=datetime.now(UTC),
            )
            crystallized_count += 1
            logger.info("Crystallized task outcome for task %s", task_id)
        except Exception as e:
            logger.warning("Failed to crystallize task outcome: %s", e)

    return ConsolidationResult(
        task_id=task_id,
        success=True,
        promoted_count=promoted_count,
        crystallized_count=crystallized_count,
        message=f"Promoted {promoted_count} memories, crystallized {crystallized_count} patterns",
    )


async def _consolidate_failure(
    task_service,
    task_id: str,
) -> ConsolidationResult:
    """Handle consolidation for failed task completion."""
    deleted_count = 0
    promoted_count = 0

    # Get all episodes from the task scope
    try:
        episodes = await task_service.list_episodes(limit=100)
    except Exception as e:
        logger.error("Failed to list task episodes: %s", e)
        return ConsolidationResult(
            task_id=task_id,
            success=False,
            message=f"Failed to list episodes: {e}",
        )

    # For failed tasks, we want to:
    # 1. Keep troubleshooting guides (they're valuable even for failures)
    # 2. Delete ephemeral memories (active_state, uncategorized)
    keep_categories = {
        MemoryCategory.TROUBLESHOOTING_GUIDE,
        MemoryCategory.CODING_STANDARD,
    }

    for episode in episodes.episodes:
        if episode.category in keep_categories:
            # Promote troubleshooting to project scope (learn from failures!)
            try:
                project_service = get_memory_service(
                    scope=MemoryScope.PROJECT,
                    scope_id="default",  # Use default project for orphaned tasks
                )
                await project_service.add_episode(
                    content=f"From failed task {task_id}: {episode.content}",
                    source=episode.source,
                    source_description=f"preserved from failed task - {episode.source_description}",
                    reference_time=datetime.now(UTC),
                )
                promoted_count += 1
                logger.debug("Preserved troubleshooting memory from failed task")
            except Exception as e:
                logger.warning("Failed to preserve memory: %s", e)
        else:
            # Delete ephemeral memories
            try:
                await task_service.delete_episode(episode.uuid)
                deleted_count += 1
                logger.debug("Deleted ephemeral memory %s from failed task", episode.uuid)
            except Exception as e:
                logger.warning("Failed to delete episode %s: %s", episode.uuid, e)

    return ConsolidationResult(
        task_id=task_id,
        success=True,
        promoted_count=promoted_count,
        deleted_count=deleted_count,
        message=f"Preserved {promoted_count} troubleshooting memories, deleted {deleted_count} ephemeral memories",
    )


async def crystallize_patterns(
    project_id: str,
    pattern_description: str,
    supporting_evidence: list[str] | None = None,
) -> bool:
    """
    Crystallize a pattern from observed task outcomes.

    Creates a new memory at project scope representing a pattern
    that has been observed across multiple task executions.

    Args:
        project_id: Project ID for the pattern
        pattern_description: Description of the observed pattern
        supporting_evidence: Optional list of supporting observations

    Returns:
        True if crystallization succeeded
    """
    service = get_memory_service(scope=MemoryScope.PROJECT, scope_id=project_id)

    content_parts = [f"Pattern: {pattern_description}"]
    if supporting_evidence:
        content_parts.append("Evidence:")
        for evidence in supporting_evidence:
            content_parts.append(f"- {evidence}")

    content = "\n".join(content_parts)

    try:
        await service.add_episode(
            content=content,
            source=MemorySource.SYSTEM,
            source_description="coding standard pattern crystallization",
            reference_time=datetime.now(UTC),
        )
        logger.info("Crystallized pattern: %s", pattern_description[:50])
        return True
    except Exception as e:
        logger.error("Failed to crystallize pattern: %s", e)
        return False
