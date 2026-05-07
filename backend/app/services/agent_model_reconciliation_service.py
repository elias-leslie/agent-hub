"""Startup reconciliation for adaptive routing metadata.

This module intentionally no longer rewrites ``agents.primary_model_id`` or
fallback chains. Agent model selection is owned by adaptive routing profiles and
manual model routes; legacy agent fields are compatibility seed material only.
"""

from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.adaptive_model_router import ensure_adaptive_routing_seed_data

logger = logging.getLogger(__name__)


async def reconcile_agent_models_to_available_providers(db: AsyncSession) -> list[str]:
    """Seed adaptive routing metadata without changing agent model assignments.

    Returns a compact status list for startup logging. Kept under the previous
    function name so old startup/test patch points remain stable during the
    migration.
    """
    changed = await ensure_adaptive_routing_seed_data(db)
    if changed:
        logger.info("Seeded/refreshed %d adaptive routing row(s)", changed)
        return [f"adaptive-routing:{changed}"]
    return []
