"""Utility functions for Agent Routing Service."""

import logging
from typing import Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.openrouter import OpenRouterAdapter

logger = logging.getLogger(__name__)


async def get_global_instructions(db: AsyncSession) -> str | None:
    """Fetch global instructions from database.

    Returns:
        Global instructions content if enabled, None otherwise.
    """
    try:
        result = await db.execute(
            text("SELECT content, enabled FROM global_instructions WHERE scope = 'global'")
        )
        row = result.fetchone()
        if row and row.enabled and row.content:
            logger.info(
                f"Global instructions fetched: enabled={row.enabled}, length={len(row.content)}"
            )
            content: str = row.content
            return content
        else:
            logger.info(f"Global instructions not available: row={row is not None}")
    except Exception as e:
        logger.warning(f"Failed to fetch global instructions: {e}")
    return None


def get_provider_for_model(model: str) -> str:
    """Determine provider from model name.

    Args:
        model: Model ID (e.g., "claude-sonnet-4-5", "gemini-3-flash")

    Returns:
        Provider name ("claude", "gemini", "openrouter", or "openai")
    """
    model_lower = model.lower()
    if model_lower.startswith("openrouter/") or model_lower.startswith("or/"):
        return "openrouter"
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    elif "gpt" in model_lower or "openai" in model_lower:
        return "openai"
    return "claude"  # Default


def get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter | OpenRouterAdapter:
    """Get adapter instance for provider.

    Args:
        provider: Provider name ("claude", "gemini", or "openrouter")

    Returns:
        Adapter instance

    Raises:
        ValueError: If provider is unknown
    """
    if provider == "claude":
        return ClaudeAdapter()
    elif provider == "gemini":
        return GeminiAdapter()
    elif provider == "openrouter":
        return OpenRouterAdapter()
    raise ValueError(f"Unknown provider: {provider}")
