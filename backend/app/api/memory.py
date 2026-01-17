"""Memory API - Knowledge graph memory management."""

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.memory import MemoryService, get_memory_service
from app.services.memory.service import MemoryContext, MemorySearchResult, MemorySource

router = APIRouter(prefix="/memory", tags=["memory"])


def get_group_id(x_group_id: Annotated[str | None, Header()] = None) -> str:
    """Get group ID from header or use default."""
    return x_group_id or "default"


def get_memory_svc(
    group_id: Annotated[str, Depends(get_group_id)],
) -> MemoryService:
    """Get memory service instance for the group."""
    return get_memory_service(group_id)


# Request/Response schemas
class AddEpisodeRequest(BaseModel):
    """Request body for adding an episode to memory."""

    content: str = Field(..., description="Content to remember")
    source: MemorySource = Field(MemorySource.CHAT, description="Source type (chat, voice, system)")
    source_description: str | None = Field(None, description="Human-readable source description")
    reference_time: datetime | None = Field(
        None, description="When the episode occurred (defaults to now)"
    )


class AddEpisodeResponse(BaseModel):
    """Response body for add episode."""

    uuid: str = Field(..., description="UUID of the created episode")
    message: str = Field(default="Episode added successfully")


class SearchResponse(BaseModel):
    """Response body for memory search."""

    query: str
    results: list[MemorySearchResult]
    count: int


class ContextResponse(BaseModel):
    """Response body for context retrieval."""

    context: MemoryContext
    formatted: str = Field(..., description="Pre-formatted context string for LLM injection")


class HealthResponse(BaseModel):
    """Response body for health check."""

    status: str
    neo4j: str
    group_id: str
    error: str | None = None


@router.post("/add", response_model=AddEpisodeResponse)
async def add_episode(
    request: AddEpisodeRequest,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> AddEpisodeResponse:
    """
    Add an episode to the knowledge graph memory.

    Episodes are processed to extract entities and relationships,
    which are stored in the knowledge graph for semantic retrieval.
    """
    try:
        uuid = await memory.add_episode(
            content=request.content,
            source=request.source,
            source_description=request.source_description,
            reference_time=request.reference_time,
        )
        return AddEpisodeResponse(uuid=uuid)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to add episode: {e}") from e


@router.get("/search", response_model=SearchResponse)
async def search_memory(
    query: Annotated[str, Query(..., description="Search query")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    limit: Annotated[int, Query(ge=1, le=100, description="Max results")] = 10,
    min_score: Annotated[float, Query(ge=0.0, le=1.0, description="Minimum relevance score")] = 0.0,
) -> SearchResponse:
    """
    Search memory for relevant episodes and facts.

    Uses semantic search combined with graph traversal to find
    relevant information from the knowledge graph.
    """
    try:
        results = await memory.search(
            query=query,
            limit=limit,
            min_score=min_score,
        )
        return SearchResponse(
            query=query,
            results=results,
            count=len(results),
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Search failed: {e}") from e


@router.get("/context", response_model=ContextResponse)
async def get_context(
    query: Annotated[str, Query(..., description="Query to find context for")],
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
    max_facts: Annotated[int, Query(ge=1, le=50, description="Maximum facts to include")] = 10,
    max_entities: Annotated[int, Query(ge=1, le=20, description="Maximum entities to include")] = 5,
) -> ContextResponse:
    """
    Get relevant context for a query, formatted for LLM injection.

    Returns facts and entities relevant to the query, along with
    a pre-formatted string suitable for system prompt injection.
    """
    try:
        context = await memory.get_context_for_query(
            query=query,
            max_facts=max_facts,
            max_entities=max_entities,
        )

        # Format context for LLM injection
        formatted_parts = []
        if context.relevant_facts:
            formatted_parts.append("Relevant facts from memory:")
            for fact in context.relevant_facts:
                formatted_parts.append(f"- {fact}")

        if context.relevant_entities:
            formatted_parts.append("\nKnown entities:")
            for entity in context.relevant_entities:
                formatted_parts.append(f"- {entity}")

        formatted = "\n".join(formatted_parts) if formatted_parts else ""

        return ContextResponse(context=context, formatted=formatted)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Context retrieval failed: {e}") from e


@router.delete("/episode/{episode_id}")
async def delete_episode(
    episode_id: str,
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> dict:
    """
    Delete an episode from memory.

    Note: This removes the episode but may leave orphaned entities
    that were only connected through this episode.
    """
    # TODO: Implement episode deletion in MemoryService
    # For now, return not implemented
    raise HTTPException(
        status_code=501,
        detail="Episode deletion not yet implemented",
    )


@router.get("/health", response_model=HealthResponse)
async def memory_health(
    memory: Annotated[MemoryService, Depends(get_memory_svc)],
) -> HealthResponse:
    """
    Check memory system health.

    Returns connection status for Neo4j and the knowledge graph.
    """
    health = await memory.health_check()
    return HealthResponse(**health)
