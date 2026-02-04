"""Models API - List available models."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
    OR_FREE_GLM,
    OR_FREE_TRINITY,
    OR_GEMINI_3_FLASH,
    OR_GEMINI_3_PRO,
    OR_GROK_4_1,
    OR_GROK_CODE,
    OR_KIMI_K2_5,
    OR_MINIMAX_2_1,
)

router = APIRouter()


class ModelInfo(BaseModel):
    """Model information."""

    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name")
    provider: str = Field(..., description="Provider: claude, gemini, or openrouter")


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]


AVAILABLE_MODELS = [
    ModelInfo(id=CLAUDE_SONNET, name="Claude Sonnet 4.5", provider="claude"),
    ModelInfo(id=CLAUDE_OPUS, name="Claude Opus 4.5", provider="claude"),
    ModelInfo(id=CLAUDE_HAIKU, name="Claude Haiku 4.5", provider="claude"),
    ModelInfo(id=GEMINI_FLASH, name="Gemini 3 Flash", provider="gemini"),
    ModelInfo(id=GEMINI_PRO, name="Gemini 3 Pro", provider="gemini"),
    # OpenRouter Models
    ModelInfo(id=OR_GROK_CODE, name="Grok Code Fast 1 (OR)", provider="openrouter"),
    ModelInfo(id=OR_GROK_4_1, name="Grok 4.1 Fast (OR)", provider="openrouter"),
    ModelInfo(id=OR_KIMI_K2_5, name="Kimi K2.5 (OR)", provider="openrouter"),
    ModelInfo(id=OR_GEMINI_3_FLASH, name="Gemini 3 Flash (OR)", provider="openrouter"),
    ModelInfo(id=OR_GEMINI_3_PRO, name="Gemini 3 Pro (OR)", provider="openrouter"),
    ModelInfo(id=OR_MINIMAX_2_1, name="MiniMax 2.1 (OR)", provider="openrouter"),
    ModelInfo(id=OR_FREE_TRINITY, name="Trinity Large (Free)", provider="openrouter"),
    ModelInfo(id=OR_FREE_GLM, name="GLM-4.5 Air (Free)", provider="openrouter"),
]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models for chat completions."""
    return ModelsResponse(models=AVAILABLE_MODELS)
