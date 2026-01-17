"""LLM Model Registry API.

Database-backed model registry endpoints for centralized model management.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import LLMModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/models", tags=["models"])


class ModelResponse(BaseModel):
    """LLM model response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    display_name: str
    provider: str
    family: str | None
    context_window: int
    max_output_tokens: int | None
    input_price_per_m: float | None
    output_price_per_m: float | None
    capabilities: dict | None
    is_deprecated: bool
    is_active: bool


class ModelsListResponse(BaseModel):
    """List models response."""

    models: list[ModelResponse]
    count: int


@router.get("", response_model=ModelsListResponse)
async def list_models(
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str | None = None,
    active_only: bool = True,
) -> ModelsListResponse:
    """
    List available LLM models.

    Args:
        provider: Filter by provider (anthropic, google)
        active_only: Only return active models (default: True)

    Returns:
        List of available models with metadata
    """
    query = select(LLMModel)

    if active_only:
        query = query.where(LLMModel.is_active == True)  # noqa: E712

    if provider:
        query = query.where(LLMModel.provider == provider)

    query = query.order_by(LLMModel.provider, LLMModel.id)

    result = await db.execute(query)
    models = result.scalars().all()

    return ModelsListResponse(
        models=[ModelResponse.model_validate(m) for m in models],
        count=len(models),
    )


@router.get("/{model_id}", response_model=ModelResponse)
async def get_model(
    model_id: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ModelResponse:
    """
    Get a specific model's details.

    Args:
        model_id: The model identifier (e.g., 'claude-sonnet-4-5')

    Returns:
        Model details including capabilities and pricing
    """
    result = await db.execute(select(LLMModel).where(LLMModel.id == model_id))
    model = result.scalar_one_or_none()

    if not model:
        raise HTTPException(
            status_code=404,
            detail=f"Model '{model_id}' not found",
        )

    return ModelResponse.model_validate(model)
