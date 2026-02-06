"""Models API - List available models."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.constants import MODEL_REGISTRY

router = APIRouter()


class ModelInfo(BaseModel):
    """Model information."""

    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name")
    alias: str = Field(..., description="Short alias for @mention")
    hint: str = Field(..., description="Brief UI hint")
    provider: str = Field(..., description="Provider: claude, gemini, or openrouter")


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]


AVAILABLE_MODELS = [ModelInfo(**entry) for entry in MODEL_REGISTRY]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models for chat completions."""
    return ModelsResponse(models=AVAILABLE_MODELS)
