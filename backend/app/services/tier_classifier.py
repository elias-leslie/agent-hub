"""Tier-based model selection for cost optimization."""

import re
from dataclasses import dataclass
from enum import IntEnum


class Tier(IntEnum):
    """
    Task complexity tiers.

    Lower tiers use faster/cheaper models, higher tiers use more capable models.
    """

    TIER_1 = 1  # Simple queries, lookups, formatting
    TIER_2 = 2  # Standard coding, explanations
    TIER_3 = 3  # Complex reasoning, multi-step tasks
    TIER_4 = 4  # Most complex tasks, architecture, deep analysis


@dataclass
class TierMapping:
    """Model mapping for a tier."""

    claude: str
    gemini: str


# Model mappings by tier
TIER_MODELS: dict[Tier, TierMapping] = {
    Tier.TIER_1: TierMapping(
        claude="claude-haiku-4-5-20250514",
        gemini="gemini-2.0-flash",
    ),
    Tier.TIER_2: TierMapping(
        claude="claude-sonnet-4-5-20250514",
        gemini="gemini-2.5-flash-preview-05-20",
    ),
    Tier.TIER_3: TierMapping(
        claude="claude-sonnet-4-5-20250514",
        gemini="gemini-2.5-pro-preview-06-05",
    ),
    Tier.TIER_4: TierMapping(
        claude="claude-opus-4-5-20250514",
        gemini="gemini-2.5-pro-preview-06-05",
    ),
}


# Complexity indicators (patterns that suggest higher tiers)
COMPLEXITY_PATTERNS = {
    Tier.TIER_4: [
        r"\barchitect\w*\b",
        r"\bdesign\s+pattern\b",
        r"\bsystem\s+design\b",
        r"\bscalability\b",
        r"\broot\s+cause\b",
        r"\bdeep\s+analysis\b",
        r"\bmulti-step\b",
        r"\bcomplex\s+(algorithm|reasoning)\b",
    ],
    Tier.TIER_3: [
        r"\brefactor\w*\b",
        r"\boptimiz\w*\b",
        r"\bintegrat\w*\b",
        r"\bdebug\w*\b",
        r"\bfix\s+bug\b",
        r"\bexplain\s+(why|how)\b",
        r"\bimplement\w*\b",
    ],
    Tier.TIER_2: [
        r"\bwrite\s+(code|function|test)\b",
        r"\bcreate\s+\w+\b",
        r"\bgenerate\b",
        r"\bconvert\b",
        r"\bupdate\b",
        r"\badd\s+\w+\b",
    ],
}


def classify_request(prompt: str, context: str | None = None) -> Tier:
    """
    Classify a request into a complexity tier.

    Uses heuristics based on keywords and prompt structure.
    Higher tiers for more complex reasoning tasks.

    Args:
        prompt: The user's prompt/message
        context: Optional additional context

    Returns:
        Tier classification
    """
    text = f"{prompt} {context or ''}".lower()

    # Check for tier 4 patterns first
    for pattern in COMPLEXITY_PATTERNS.get(Tier.TIER_4, []):
        if re.search(pattern, text, re.IGNORECASE):
            return Tier.TIER_4

    # Check for tier 3 patterns
    for pattern in COMPLEXITY_PATTERNS.get(Tier.TIER_3, []):
        if re.search(pattern, text, re.IGNORECASE):
            return Tier.TIER_3

    # Check for tier 2 patterns
    for pattern in COMPLEXITY_PATTERNS.get(Tier.TIER_2, []):
        if re.search(pattern, text, re.IGNORECASE):
            return Tier.TIER_2

    # Check for length - longer prompts often need more reasoning
    if len(text) > 2000:
        return Tier.TIER_3
    elif len(text) > 500:
        return Tier.TIER_2

    # Default to tier 1 for simple queries
    return Tier.TIER_1


def get_model_for_tier(tier: Tier, provider: str = "claude") -> str:
    """
    Get the appropriate model for a tier and provider.

    Args:
        tier: Complexity tier
        provider: Provider name ("claude" or "gemini")

    Returns:
        Model identifier string
    """
    mapping = TIER_MODELS.get(tier, TIER_MODELS[Tier.TIER_2])

    if provider == "gemini":
        return mapping.gemini
    return mapping.claude


def classify_and_select_model(
    prompt: str,
    context: str | None = None,
    provider: str = "claude",
    explicit_model: str | None = None,
) -> tuple[Tier, str]:
    """
    Classify request and select appropriate model.

    If explicit_model is provided, uses that instead of tier-based selection.

    Args:
        prompt: User's prompt
        context: Optional context
        provider: Target provider
        explicit_model: Override model if specified

    Returns:
        Tuple of (tier, model_name)
    """
    tier = classify_request(prompt, context)

    if explicit_model:
        return tier, explicit_model

    return tier, get_model_for_tier(tier, provider)
