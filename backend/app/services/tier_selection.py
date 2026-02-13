"""Tier-based model selection for auto-routing."""

import logging

from app.adapters.base import Message
from app.services.model_selector import (
    QualityPreference,
    classify_complexity,
    detect_category_weights,
    detect_required_capabilities,
    select_model,
)

logger = logging.getLogger(__name__)


def select_model_by_tier(
    messages: list[Message],
    primary_provider: str,
    preference: QualityPreference = QualityPreference.STANDARD,
) -> str:
    """Select model based on message complexity tier.

    Args:
        messages: Conversation messages
        primary_provider: Primary provider to use
        preference: Quality preference for model selection

    Returns:
        Selected model identifier
    """
    # Extract prompt from last user message for classification
    prompt = ""
    for msg in reversed(messages):
        if msg.role == "user":
            # Handle both str and list content
            if isinstance(msg.content, str):
                prompt = msg.content
            else:
                # Extract text from content blocks
                prompt = " ".join(
                    block.get("text", "")
                    for block in msg.content
                    if isinstance(block, dict) and block.get("type") == "text"
                )
            break

    # Use score-based selection
    complexity = classify_complexity(prompt)
    category_weights = detect_category_weights(prompt=prompt)
    required_capabilities = detect_required_capabilities(prompt=prompt)

    model_entry = select_model(
        complexity=complexity,
        preference=preference,
        category_weights=category_weights,
        required_capabilities=required_capabilities,
        provider=primary_provider,
    )

    logger.info(f"Auto-tier selected: tier={complexity}, model={model_entry.id}")
    return model_entry.id
