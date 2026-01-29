"""Celery task for tier optimization."""

import asyncio
import logging

from app.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.tasks.tier_optimizer_task.run_tier_optimizer")
def run_tier_optimizer() -> dict[str, object]:
    """Celery task to run tier optimization.

    Runs daily at 2am UTC via celery beat.
    Promotes high-utility episodes, demotes low-utility/zombie episodes.

    Returns:
        Dict with optimization statistics
    """
    from app.services.memory.tier_optimizer import optimize_tiers

    try:
        result = asyncio.run(optimize_tiers())
        logger.info(
            "Tier optimization complete: %d demotions, %d promotions",
            result.get("demotions", 0),
            result.get("promotions", 0),
        )
        return {"status": "success", **result}
    except Exception as e:
        logger.error(f"Tier optimization task failed: {e}")
        return {"status": "error", "error": str(e)}
