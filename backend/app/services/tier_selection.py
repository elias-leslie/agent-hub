"""Tier-based model selection for auto-routing."""

import logging

from app.adapters.base import Message
from app.services.tier_classifier import classify_request, get_model_for_tier

logger = logging.getLogger(__name__)


def select_model_by_tier(messages: list[Message], primary_provider: str) -> str:
    """Select model based on message complexity tier.

    Args:
        messages: Conversation messages
        primary_provider: Primary provider to use

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
    tier = classify_request(prompt)
    model = get_model_for_tier(tier, primary_provider)
    logger.info(f"Auto-tier selected: tier={tier}, model={model}")
    return model
