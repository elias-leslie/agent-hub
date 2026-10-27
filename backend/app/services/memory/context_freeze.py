"""Per-session reuse of the canonical context delivery.

Provider prompt caches (Codex ``instructions``, Anthropic system blocks) only hit
when the system prompt is identical across the turns of one chat. The canonical
delivery is query-dependent (selected references, continuity), so rebuilding it
every turn changes the prompt every turn. The first delivery of a session is
kept for a bounded time and reused for later turns; it is rebuilt when the TTL
expires or when anything that selects context other than the query changes.
Redis being unavailable simply means no reuse.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import TYPE_CHECKING

import redis.asyncio as redis

from app.config import settings

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.services.runtime_context import (
        CanonicalContextDeliveryRequest,
        CanonicalContextDeliveryResponse,
    )

logger = logging.getLogger(__name__)

_KEY_PREFIX = "agent-hub:context-freeze:"
# Fields that vary per turn and must not select a different frozen delivery.
_PER_TURN_FIELDS = {"query", "task", "client_metadata"}
_client: redis.Redis | None = None


def _redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.agent_hub_redis_url, encoding="utf-8", decode_responses=True
        )
    return _client


async def freeze_key(
    db: AsyncSession, request: CanonicalContextDeliveryRequest
) -> str | None:
    """Key for this session's delivery, or None when reuse does not apply."""
    session_id = request.session_id
    if (
        settings.agent_hub_context_freeze_ttl_seconds <= 0
        or not session_id
        or session_id.startswith("ephemeral:")
    ):
        return None
    from app.services.context_governance import session_workflows

    # A workflow activated mid-session must change the selection immediately.
    workflows = await session_workflows(db, request.consumer_surface, session_id)
    selection = request.model_dump(mode="json", exclude=_PER_TURN_FIELDS)
    selection["activated_workflows"] = sorted(workflows)
    digest = hashlib.sha256(
        json.dumps(selection, sort_keys=True, default=str).encode()
    ).hexdigest()
    return f"{_KEY_PREFIX}{session_id}:{digest}"


async def load_frozen_delivery(key: str) -> CanonicalContextDeliveryResponse | None:
    from app.services.runtime_context import CanonicalContextDeliveryResponse

    try:
        raw = await _redis().get(key)
        return CanonicalContextDeliveryResponse.model_validate_json(raw) if raw else None
    except Exception as exc:
        logger.warning("Context freeze read failed: %s", exc)
        return None


async def store_frozen_delivery(
    key: str, delivery: CanonicalContextDeliveryResponse
) -> None:
    if delivery.status != "ok":
        return
    try:
        await _redis().set(
            key,
            delivery.model_copy(update={"preview": None}).model_dump_json(),
            ex=settings.agent_hub_context_freeze_ttl_seconds,
        )
    except Exception as exc:
        logger.warning("Context freeze write failed: %s", exc)
