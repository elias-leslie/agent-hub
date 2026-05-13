"""Startup compatibility hook for agent model assignments.

Agent model selection is stored directly on the agent row. Startup must not
create secondary routing tables or rewrite model chains.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession


async def reconcile_agent_models_to_available_providers(db: AsyncSession) -> list[str]:
    """Return no changes after deleting secondary routing metadata.

    Returns a compact status list for startup logging. Kept under the previous
    function name so old startup/test patch points remain stable during the
    routing cleanup.
    """
    _ = db
    return []
