from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.helpers.agent_preview import build_agent_preview
from app.api.memory_agent_handlers import build_progressive_context_response
from app.services.memory.service import MemoryScope
from app.services.memory.settings import MemorySettingsDTO
from app.services.runtime_context import (
    CanonicalContextBlock,
    CanonicalContextDeliveryResponse,
    CanonicalContextMetadata,
    CanonicalContextProvenance,
    CanonicalPolicyCompleteness,
)


def _delivery() -> CanonicalContextDeliveryResponse:
    rendered = "Canonical operator prompt\nFull mandate"
    return CanonicalContextDeliveryResponse(
        delivery_id="delivery-parity",
        artifact_id="context-parity",
        generated_at=datetime.now(UTC),
        status="ok",
        payload_hash=hashlib.sha256(rendered.encode()).hexdigest(),
        metadata=CanonicalContextMetadata(
            consumer_surface="parity",
            consumer_profile="agent_runtime",
            query="same query",
            query_hash=hashlib.sha256(b"same query").hexdigest(),
        ),
        blocks=[
            CanonicalContextBlock(
                order=0,
                block_id="prompt:operator",
                kind="prompt",
                authority="operator_instruction",
                required=True,
                title="Operator",
                content="Canonical operator prompt",
                estimated_tokens=4,
                provenance=CanonicalContextProvenance(
                    source_type="prompt",
                    source_id="operator",
                    source_revision="sha256:prompt",
                    origin="auto",
                ),
            ),
            CanonicalContextBlock(
                order=1,
                block_id="memory:11111111-1111-1111-1111-111111111111",
                kind="mandate",
                authority="operator_mandate",
                required=True,
                title="Mandate",
                content="Full mandate",
                estimated_tokens=2,
                provenance=CanonicalContextProvenance(
                    source_type="memory",
                    source_id="11111111-1111-1111-1111-111111111111",
                    source_revision="v1:sha256:mandate",
                    origin="auto",
                    scope="global",
                    review_status="clean",
                ),
            ),
        ],
        rendered=rendered,
        estimated_tokens=6,
        required_policy=CanonicalPolicyCompleteness(
            state="complete",
            required_source_ids=["operator", "11111111-1111-1111-1111-111111111111"],
            delivered_source_ids=["operator", "11111111-1111-1111-1111-111111111111"],
        ),
    )


def _async_session_cm() -> MagicMock:
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=AsyncMock())
    context.__aexit__ = AsyncMock(return_value=None)
    return context


@pytest.mark.asyncio
async def test_internal_preview_progressive_and_mcp_preserve_block_hash_parity() -> None:
    delivery = _delivery()
    settings = MemorySettingsDTO(enabled=True, budget_enabled=False, total_budget=0)

    from app.services.memory.context_injector_ops import run_injection_operation

    with patch(
        "app.services.memory.context_injector_ops._build_delivery",
        new=AsyncMock(return_value=(delivery, "BASELINE")),
    ):
        internal_messages, internal_context = await run_injection_operation(
            messages=[{"role": "user", "content": "same query"}],
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            query="same query",
            variant=None,
            session_id="session",
            external_id=None,
            project_id=None,
            collect_metrics=False,
            task_type=None,
            phase=None,
            include_continuity=True,
            memory_config=None,
            current_branch=None,
            consumer_profile="agent_runtime",
            consumer_agent_slug="reviewer",
            consumer_tags=None,
            db=AsyncMock(),
        )

    agent = SimpleNamespace(
        id=1,
        slug="reviewer",
        name="Reviewer",
        system_prompt="Review carefully",
        memory_config=None,
        primary_model_id="codex/gpt-5.4",
    )
    with (
        patch(
            "app.api.helpers.agent_preview.build_canonical_context_delivery",
            new=AsyncMock(return_value=delivery),
        ),
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.api.helpers.agent_preview.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
    ):
        preview = await build_agent_preview(AsyncMock(), agent, task_type="chat")

    with (
        patch(
            "app.api.memory_agent_handlers.async_session",
            return_value=_async_session_cm(),
        ),
        patch(
            "app.api.memory_agent_handlers.get_memory_settings",
            new=AsyncMock(return_value=settings),
        ),
        patch(
            "app.api.memory_agent_handlers.assign_variant",
            return_value="BASELINE",
        ),
        patch(
            "app.api.memory_agent_handlers.build_canonical_context_delivery",
            new=AsyncMock(return_value=delivery),
        ),
        patch(
            "app.api.memory_agent_handlers.track_and_record_metrics",
            new=AsyncMock(),
        ),
    ):
        progressive = await build_progressive_context_response(
            query="same query",
            scope=MemoryScope.GLOBAL,
            scope_id=None,
            debug=False,
            include_global=True,
            task_type=None,
        )

    import mcp_server

    with (
        patch("mcp_server.async_session", return_value=_async_session_cm()),
        patch(
            "mcp_server.build_canonical_context_delivery",
            new=AsyncMock(return_value=delivery),
        ),
    ):
        mcp_delivery = await mcp_server._get_canonical_context_delivery("same query")

    expected_block_ids = [block.block_id for block in delivery.blocks]
    assert internal_context.debug_info["canonical_payload_hash"] == delivery.payload_hash
    assert internal_context.debug_info["canonical_block_ids"] == expected_block_ids
    from app.services.memory.context_injector_ops import has_verified_canonical_context

    assert has_verified_canonical_context(internal_messages) is True
    assert internal_messages[0]["content"].count(delivery.rendered) == 1
    assert preview["canonical_context"]["payload_hash"] == delivery.payload_hash
    assert preview["canonical_context"]["block_ids"] == expected_block_ids
    assert progressive.canonical_context is not None
    assert progressive.canonical_context["payload_hash"] == delivery.payload_hash
    assert progressive.canonical_context["block_ids"] == expected_block_ids
    assert mcp_delivery.payload_hash == delivery.payload_hash
    assert [block.block_id for block in mcp_delivery.blocks] == expected_block_ids
