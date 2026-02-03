"""Helper functions for episode creation."""

from __future__ import annotations

import logging
from typing import Any

from .ingestion_config import IngestionConfig

logger = logging.getLogger(__name__)


def build_source_description(config: IngestionConfig) -> str:
    """Build source description with metadata."""
    parts = [
        f"tier:{config.tier.value}",
    ]
    return " ".join(parts)


def derive_injection_tier(config: IngestionConfig) -> str:
    """Derive injection_tier from config settings."""
    if config.is_golden:
        return "mandate"
    tier_value = config.tier.value
    if tier_value in ("always", "mandate"):
        return "mandate"
    if tier_value in ("high", "guardrail"):
        return "guardrail"
    return "reference"


async def set_token_count(graphiti: "Any", episode_uuid: str, token_count: int) -> bool:
    """Set token_count property on an Episodic node."""
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.token_count = $token_count
    RETURN e.uuid AS uuid
    """
    try:
        records, _, _ = await graphiti.driver.execute_query(
            query,
            uuid=episode_uuid,
            token_count=token_count,
        )
        return bool(records)
    except Exception as e:
        logger.warning("Failed to set token_count for %s: %s", episode_uuid[:8], e)
        return False
