"""Recent Activity (cross-session continuity) is not injected unless an agent opts in."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory import context_injector_ops
from app.services.memory.context_builder_settings import (
    normalize_memory_config,
    resolve_continuity_settings,
)
from app.services.memory.memory_models import MemoryScope
from app.services.memory.settings import _defaults_dto
from app.services.runtime_context import CanonicalContextDeliveryRequest


def test_defaults_are_off_everywhere() -> None:
    assert _defaults_dto().continuity_enabled is False
    assert CanonicalContextDeliveryRequest(consumer_surface="agent_runtime").include_continuity is False
    assert normalize_memory_config({})["continuity_enabled"] is False  # type: ignore[index]
    assert resolve_continuity_settings(_defaults_dto(), None)[0] is False


async def _requested(memory_config: dict[str, Any] | None) -> CanonicalContextDeliveryRequest:
    seen: list[CanonicalContextDeliveryRequest] = []

    async def _build(db: Any, request: CanonicalContextDeliveryRequest) -> object:
        seen.append(request)
        return object()

    with (
        patch.object(context_injector_ops, "get_memory_settings", new=AsyncMock(return_value=_defaults_dto())),
        patch("app.services.memory.context_injector_ops.context_freeze.freeze_key", new=AsyncMock(return_value=None)),
        patch("app.services.runtime_context.build_canonical_context_delivery", new=_build),
        patch("app.services.canonical_context_adapters.require_canonical_context", new=lambda d: d),
    ):
        await context_injector_ops._build_delivery(
            db=AsyncMock(), messages=[], scope=MemoryScope.GLOBAL, scope_id=None, query="q", variant=None,
            session_id=None, external_id=None, project_id="agent-hub", task_type=None, phase=None,
            include_continuity=True, memory_config=memory_config, current_branch=None,
            consumer_surface="agent_runtime", consumer_profile=None, consumer_agent_slug="coder",
            consumer_tags=None, include_prompts=True, include_memories=True,
        )
    return seen[0]


@pytest.mark.asyncio
async def test_agent_without_config_gets_no_recent_activity() -> None:
    assert (await _requested(None)).include_continuity is False


@pytest.mark.asyncio
async def test_agent_config_without_the_key_gets_no_recent_activity() -> None:
    assert (await _requested({"include_mandates": True})).include_continuity is False


@pytest.mark.asyncio
async def test_agent_can_opt_in_through_its_own_config() -> None:
    assert (await _requested({"continuity_enabled": True})).include_continuity is True
