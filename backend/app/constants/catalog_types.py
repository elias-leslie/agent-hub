"""Data types and scoring weights for the model catalog."""

from __future__ import annotations

from dataclasses import dataclass, field

# Scoring category weights for composite calculation
SCORE_WEIGHTS: dict[str, float] = {
    "coding": 0.25,
    "reasoning": 0.20,
    "planning": 0.15,
    "tool_use": 0.15,
    "instruction": 0.15,
    "design": 0.10,
}

@dataclass(frozen=True)
class ModelScores:
    """Benchmark scores normalized to 0-100 scale."""

    coding: int  # SWE-Bench Verified, HumanEval+, LiveCodeBench
    reasoning: int  # GPQA Diamond, MATH-500, ARC-AGI
    planning: int  # MEWC, BrowseComp, agentic evals
    tool_use: int  # BFCL, function calling accuracy
    instruction: int  # IFEval, MT-Bench, AlpacaEval
    design: int  # DesignBench, Design2Code, MMMU-Pro

    @property
    def composite(self) -> float:
        """Weighted average across all categories."""
        return round(
            self.coding * SCORE_WEIGHTS["coding"]
            + self.reasoning * SCORE_WEIGHTS["reasoning"]
            + self.planning * SCORE_WEIGHTS["planning"]
            + self.tool_use * SCORE_WEIGHTS["tool_use"]
            + self.instruction * SCORE_WEIGHTS["instruction"]
            + self.design * SCORE_WEIGHTS["design"],
            1,
        )


@dataclass(frozen=True)
class ModelCost:
    """Pricing in USD per million tokens."""

    input_per_m: float
    output_per_m: float
    # Service tier cost multipliers (e.g. OpenAI flex/priority tiers)
    service_tiers: dict[str, float] = field(default_factory=lambda: {"default": 1.0})
    # Prompt caching pricing (Anthropic)
    cache_read_per_million: float | None = None
    cache_write_per_million: float | None = None


@dataclass(frozen=True)
class ModelCapabilities:
    """Model output and input capabilities."""

    can_generate_images: bool = False
    has_vision: bool = False
    can_edit_images: bool = False
    has_thinking: bool = False
    supports_pdf: bool = False
    supports_audio: bool = False
    supports_tool_execution: bool = False
    supports_verbosity: bool = False
    supports_xhigh: bool = False
    supports_session_cache: bool = False
    max_output_tokens: int = 8192


@dataclass(frozen=True)
class ModelEntry:
    """Rich model registry entry with scores, costs, and capabilities."""

    id: str
    alias: str
    name: str
    hint: str
    provider: str
    scores: ModelScores
    cost: ModelCost
    context_window: int
    speed_tier: str  # "fast", "medium", "slow"
    capabilities: ModelCapabilities = field(default_factory=ModelCapabilities)
    release_date: str | None = None
    knowledge_cutoff: str | None = None
    family: str | None = None
