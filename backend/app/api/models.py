"""Models API - List available models."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
)

router = APIRouter()


class ModelInfo(BaseModel):
    """Model information."""

    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name")
    provider: str = Field(..., description="Provider: claude or gemini")


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]


AVAILABLE_MODELS = [
    ModelInfo(id=CLAUDE_SONNET, name="Claude Sonnet 4.5", provider="claude"),
    ModelInfo(id=CLAUDE_OPUS, name="Claude Opus 4.5", provider="claude"),
    ModelInfo(id=CLAUDE_HAIKU, name="Claude Haiku 4.5", provider="claude"),
    ModelInfo(id=GEMINI_FLASH, name="Gemini 3 Flash", provider="gemini"),
    ModelInfo(id=GEMINI_PRO, name="Gemini 3 Pro", provider="gemini"),
]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models for chat completions."""
    return ModelsResponse(models=AVAILABLE_MODELS)
