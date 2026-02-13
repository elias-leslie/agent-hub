"""Score-based model selection for intelligent routing."""

from __future__ import annotations

import re
from enum import IntEnum, StrEnum

from app.constants import MODEL_CATALOG, MODEL_CATALOG_BY_ID, SCORE_WEIGHTS, ModelEntry


class ComplexityTier(IntEnum):
    """Task complexity tiers based on reasoning requirements."""
    TIER_1 = 1  # Simple queries, lookups, formatting
    TIER_2 = 2  # Standard coding, explanations
    TIER_3 = 3  # Complex reasoning, multi-step tasks
    TIER_4 = 4  # Most complex tasks, architecture, deep analysis


class QualityPreference(StrEnum):
    """Quality vs cost preference for model selection."""
    ECONOMY = "economy"  # Minimize cost
    STANDARD = "standard"  # Balance quality and cost
    ADVANCED = "advanced"  # Maximize quality


# Minimum composite scores required for each tier
MIN_COMPOSITE = {ComplexityTier.TIER_1: 40, ComplexityTier.TIER_2: 60, ComplexityTier.TIER_3: 72, ComplexityTier.TIER_4: 79}

# Complexity detection patterns (inherited from tier_classifier)
COMPLEXITY_PATTERNS = {
    ComplexityTier.TIER_4: [r"\barchitect\w*\b", r"\bdesign\s+pattern\b", r"\bsystem\s+design\b", r"\bscalability\b", r"\broot\s+cause\b", r"\bdeep\s+analysis\b", r"\bmulti-step\b", r"\bcomplex\s+(algorithm|reasoning)\b"],
    ComplexityTier.TIER_3: [r"\brefactor\w*\b", r"\boptimiz\w*\b", r"\bintegrat\w*\b", r"\bdebug\w*\b", r"\bfix\s+bug\b", r"\bexplain\s+(why|how)\b", r"\bimplement\w*\b"],
    ComplexityTier.TIER_2: [r"\bwrite\s+(a\s+)?(code|function|test|script|class)\b", r"\bcreate\s+(a\s+)?\w+\b", r"\bgenerate\b", r"\bconvert\b", r"\bupdate\b", r"\badd\s+\w+\b", r"\bfunction\s+to\b"],
}


def classify_complexity(prompt: str, context: str | None = None) -> ComplexityTier:
    """Classify request complexity into a tier using heuristics."""
    text = f"{prompt} {context or ''}".lower()
    # Check patterns in order of complexity
    for tier in [ComplexityTier.TIER_4, ComplexityTier.TIER_3, ComplexityTier.TIER_2]:
        for pattern in COMPLEXITY_PATTERNS.get(tier, []):
            if re.search(pattern, text, re.IGNORECASE):
                return tier
    # Length-based fallback
    if len(text) > 2000:
        return ComplexityTier.TIER_3
    elif len(text) > 500:
        return ComplexityTier.TIER_2
    return ComplexityTier.TIER_1


def detect_category_weights(agent_slug: str | None = None, prompt: str | None = None) -> dict[str, float]:
    """Detect scoring category weights from agent and prompt context."""
    weights = SCORE_WEIGHTS.copy()
    # Agent-based adjustments
    if agent_slug:
        slug_lower = agent_slug.lower()
        if slug_lower in ("coder", "debugger"):
            weights["coding"] = 0.40
        elif slug_lower in ("planner", "architect"):
            weights["planning"] = 0.35
        elif slug_lower == "reviewer":
            weights["reasoning"] = 0.35
        elif slug_lower == "designer":
            weights["design"] = 0.40
    # Prompt keyword detection
    if prompt:
        prompt_lower = prompt.lower()
        if re.search(r"\b(generate|create)\s+\w*\s*(image|picture|mockup|design)\b", prompt_lower):
            weights["design"] = 0.40
        elif re.search(r"\b(analyze|reason|explain\s+why)\b", prompt_lower):
            weights["reasoning"] = 0.35
        elif re.search(r"\b(write\s+code|implement|fix\s+bug)\b", prompt_lower):
            weights["coding"] = 0.40
        elif re.search(r"\b(plan|break\s+down|organize)\b", prompt_lower):
            weights["planning"] = 0.35
    # Normalize to sum to 1.0
    total = sum(weights.values())
    return {k: v / total for k, v in weights.items()}


def detect_required_capabilities(prompt: str | None = None, agent_slug: str | None = None) -> dict[str, bool]:
    """Detect required model capabilities from context."""
    required = {}
    if prompt:
        prompt_lower = prompt.lower()
        if re.search(r"\b(generate|create)\s+\w*\s*(image|picture|photo)\b", prompt_lower):
            required["can_generate_images"] = True
        if re.search(r"\b(look\s+at|analyze|see)\s+(this\s+)?(image|screenshot|picture)\b", prompt_lower):
            required["has_vision"] = True
        if re.search(r"\bedit\s+(this\s+)?(image|photo)\b", prompt_lower):
            required["can_edit_images"] = True
    return required


def filter_by_capabilities(models: list[ModelEntry], required: dict[str, bool]) -> list[ModelEntry]:
    """Filter models to only those with required capabilities."""
    if not required:
        return models
    return [m for m in models if all(getattr(m.capabilities, cap, False) for cap in required)]


def weighted_score(model: ModelEntry, category_weights: dict[str, float]) -> float:
    """Calculate weighted score for a model given category weights."""
    return float(sum(getattr(model.scores, cat) * weight for cat, weight in category_weights.items()))


def select_model(
    complexity: ComplexityTier,
    preference: QualityPreference = QualityPreference.STANDARD,
    category_weights: dict[str, float] | None = None,
    required_capabilities: dict[str, bool] | None = None,
    provider: str | None = None,
) -> ModelEntry:
    """Select best model based on complexity, preference, and category."""
    if category_weights is None:
        category_weights = SCORE_WEIGHTS
    min_threshold = MIN_COMPOSITE[complexity]
    models = MODEL_CATALOG.copy()
    # Apply filters
    if required_capabilities:
        models = filter_by_capabilities(models, required_capabilities)
    if provider:
        models = [m for m in models if m.provider == provider]
    # Try with threshold, relax if no candidates
    for attempt in range(3):
        current_threshold = min_threshold - (attempt * 10)
        candidates = [m for m in models if m.scores.composite >= current_threshold]
        if not candidates:
            continue
        # Apply preference
        if preference == QualityPreference.ECONOMY:
            candidates.sort(key=lambda m: m.cost.input_per_m + m.cost.output_per_m)
            return candidates[0]
        elif preference == QualityPreference.STANDARD:
            def score_per_cost(m: ModelEntry) -> float:
                total_cost = m.cost.input_per_m + m.cost.output_per_m
                return weighted_score(m, category_weights) / (total_cost if total_cost > 0 else 0.01)
            candidates.sort(key=score_per_cost, reverse=True)
            return candidates[0]
        else:  # ADVANCED
            candidates.sort(key=lambda m: weighted_score(m, category_weights), reverse=True)
            return candidates[0]
    # Last resort: return highest scoring model available
    if not models:
        models = MODEL_CATALOG
    models.sort(key=lambda m: m.scores.composite, reverse=True)
    return models[0]


def escalate_preference(preference: QualityPreference) -> QualityPreference | None:
    """Escalate quality preference one level up on failure.

    Returns None if already at highest tier (advanced).
    """
    escalation = {
        QualityPreference.ECONOMY: QualityPreference.STANDARD,
        QualityPreference.STANDARD: QualityPreference.ADVANCED,
    }
    return escalation.get(preference)


def find_equivalent(model_id: str, target_provider: str) -> str | None:
    """Find closest equivalent model in target provider by composite score."""
    if model_id not in MODEL_CATALOG_BY_ID:
        return None
    source_score = MODEL_CATALOG_BY_ID[model_id].scores.composite
    candidates = [m for m in MODEL_CATALOG if m.provider == target_provider]
    if not candidates:
        return None
    candidates.sort(key=lambda m: abs(m.scores.composite - source_score))
    return candidates[0].id


def select_model_for_request(
    prompt: str,
    agent_slug: str | None = None,
    preference: QualityPreference = QualityPreference.STANDARD,
    provider: str | None = None,
) -> ModelEntry:
    """Full pipeline: classify complexity → detect category → detect capabilities → select."""
    return select_model(
        complexity=classify_complexity(prompt),
        preference=preference,
        category_weights=detect_category_weights(agent_slug, prompt),
        required_capabilities=detect_required_capabilities(prompt, agent_slug),
        provider=provider,
    )
