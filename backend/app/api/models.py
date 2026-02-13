"""Models API - List available models with scores, costs, and capabilities."""

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.constants import MODEL_CATALOG

router = APIRouter()


class ModelScoresInfo(BaseModel):
    """Benchmark scores normalized to 0-100."""

    coding: int
    reasoning: int
    planning: int
    tool_use: int
    instruction: int
    design: int
    composite: float


class ModelCostInfo(BaseModel):
    """Pricing in USD per million tokens."""

    input_per_m: float
    output_per_m: float


class ModelCapabilitiesInfo(BaseModel):
    """Model capabilities."""

    can_generate_images: bool
    has_vision: bool
    can_edit_images: bool


class ModelInfo(BaseModel):
    """Full model information."""

    id: str = Field(..., description="Model identifier")
    name: str = Field(..., description="Display name")
    alias: str = Field(..., description="Short alias for @mention")
    hint: str = Field(..., description="Brief UI hint")
    provider: str = Field(..., description="Provider name")
    scores: ModelScoresInfo
    cost: ModelCostInfo
    context_window: int
    speed_tier: str
    capabilities: ModelCapabilitiesInfo


class ModelsResponse(BaseModel):
    """Response body for models list."""

    models: list[ModelInfo]


AVAILABLE_MODELS = [
    ModelInfo(
        id=e.id, name=e.name, alias=e.alias, hint=e.hint, provider=e.provider,
        scores=ModelScoresInfo(
            coding=e.scores.coding, reasoning=e.scores.reasoning,
            planning=e.scores.planning, tool_use=e.scores.tool_use,
            instruction=e.scores.instruction, design=e.scores.design,
            composite=e.scores.composite,
        ),
        cost=ModelCostInfo(input_per_m=e.cost.input_per_m, output_per_m=e.cost.output_per_m),
        context_window=e.context_window, speed_tier=e.speed_tier,
        capabilities=ModelCapabilitiesInfo(
            can_generate_images=e.capabilities.can_generate_images,
            has_vision=e.capabilities.has_vision,
            can_edit_images=e.capabilities.can_edit_images,
        ),
    )
    for e in MODEL_CATALOG
]


@router.get("/models", response_model=ModelsResponse)
async def list_models() -> ModelsResponse:
    """List available models for chat completions."""
    return ModelsResponse(models=AVAILABLE_MODELS)
