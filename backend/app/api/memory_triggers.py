"""Memory API - Triggered References Endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from .memory_schemas import (
    PhaseTriggeredReferenceItem,
    PhaseTriggeredReferencesResponse,
    TriggeredReferenceItem,
    TriggeredReferencesResponse,
)

router = APIRouter()


@router.get("/triggered-references", response_model=TriggeredReferencesResponse)
async def get_triggered_references_endpoint(
    task_type: Annotated[
        str, Query(..., description="Task type to match against trigger_task_types")
    ],
) -> TriggeredReferencesResponse:
    """
    Get reference episodes triggered by a specific task_type.

    Returns reference-tier episodes where the task_type is in their trigger_task_types.
    Used for context-aware reference injection in st work and autonomous execution.

    Example: GET /triggered-references?task_type=database
    Returns all references with "database" in their trigger_task_types.
    """
    from app.services.memory.memory_client import get_triggered_references

    try:
        refs = await get_triggered_references(task_type)
        return TriggeredReferencesResponse(
            task_type=task_type,
            references=[TriggeredReferenceItem(**r) for r in refs],
            count=len(refs),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get triggered references: {e}",
        ) from e


@router.get("/phase-triggered-references", response_model=PhaseTriggeredReferencesResponse)
async def get_phase_triggered_references_endpoint(
    phase: Annotated[str, Query(..., description="Subtask phase to match against trigger_phases")],
) -> PhaseTriggeredReferencesResponse:
    """
    Get reference episodes triggered by a specific subtask phase.

    Returns reference-tier episodes where the phase is in their trigger_phases.
    Used for context-aware reference injection in st context --subtask.

    Example: GET /phase-triggered-references?phase=backend
    Returns all references with "backend" in their trigger_phases.
    """
    from app.services.memory.memory_client import get_phase_triggered_references

    try:
        refs = await get_phase_triggered_references(phase)
        return PhaseTriggeredReferencesResponse(
            phase=phase,
            references=[PhaseTriggeredReferenceItem(**r) for r in refs],
            count=len(refs),
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get phase triggered references: {e}",
        ) from e
