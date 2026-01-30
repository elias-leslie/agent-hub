"""Memory episode rating endpoints - ACE-aligned agent citation feedback."""

import uuid as uuid_module

from fastapi import APIRouter, HTTPException

from .memory_schemas import RateEpisodeRequest, RateEpisodeResponse

router = APIRouter()


@router.post(
    "/episodes/{uuid}/rating",
    response_model=RateEpisodeResponse,
)
async def rate_episode(
    uuid: str,
    request: RateEpisodeRequest,
) -> RateEpisodeResponse:
    """
    Rate a memory episode as helpful, harmful, or used.

    This endpoint is used by agents to provide feedback on memory citations.
    Ratings flow to Neo4j Episodic nodes for ACE-aligned tier optimization:
    - **helpful**: Increments helpful_count (promotes episode after 5+)
    - **harmful**: Increments harmful_count (demotes episode after 3+)
    - **used**: Increments referenced_count (neutral signal)

    Called by SummitFlow after subtask execution to rate cited memories.
    """
    from app.services.memory import track_harmful, track_helpful, track_referenced

    try:
        uuid_module.UUID(uuid)
    except ValueError as e:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid UUID format: {uuid}",
        ) from e

    try:
        if request.rating.value == "helpful":
            track_helpful(uuid)
        elif request.rating.value == "harmful":
            track_harmful(uuid)
        else:  # USED
            track_referenced(uuid)

        return RateEpisodeResponse(
            success=True,
            uuid=uuid,
            rating=request.rating.value,
            message=f"Rated episode as {request.rating.value}",
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to rate episode: {e}",
        ) from e
