from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.helpers.agent_preview import _build_budget_telemetry, build_agent_preview
from app.services.memory.settings import MemorySettingsDTO
from app.services.runtime_context import (
    CanonicalContextBlock,
    CanonicalContextDeliveryResponse,
    CanonicalContextMetadata,
    CanonicalContextProvenance,
    CanonicalPolicyCompleteness,
)
from app.services.runtime_prompt_stack import RuntimePromptSection


def _agent(*, memory_config=None):
    return SimpleNamespace(
        id=1,
        slug="reviewer",
        name="Reviewer",
        system_prompt="Review carefully.",
        memory_config=memory_config,
        primary_model_id="codex/gpt-5.4",
    )


def _delivery() -> CanonicalContextDeliveryResponse:
    rendered = "## Operator\nCanonical policy"
    return CanonicalContextDeliveryResponse(
        delivery_id="delivery-preview",
        artifact_id="context-preview",
        generated_at=datetime.now(UTC),
        status="ok",
        payload_hash=hashlib.sha256(rendered.encode()).hexdigest(),
        metadata=CanonicalContextMetadata(
            consumer_surface="agent_preview",
            consumer_profile="agent_preview",
            query="preview",
            query_hash=hashlib.sha256(b"preview").hexdigest(),
        ),
        blocks=[
            CanonicalContextBlock(
                order=0,
                block_id="prompt:operator",
                kind="prompt",
                authority="operator_instruction",
                required=True,
                title="Operator",
                content="Canonical policy",
                estimated_tokens=2,
                provenance=CanonicalContextProvenance(
                    source_type="prompt",
                    source_id="operator",
                    source_revision="sha256:operator",
                    origin="auto",
                ),
            )
        ],
        rendered=rendered,
        estimated_tokens=3,
        required_policy=CanonicalPolicyCompleteness(
            state="complete",
            required_source_ids=["operator"],
            delivered_source_ids=["operator"],
        ),
    )


def _settings() -> MemorySettingsDTO:
    return MemorySettingsDTO(enabled=True, budget_enabled=False, total_budget=0)


@pytest.mark.asyncio
async def test_preview_places_canonical_context_before_agent_specific_prompt() -> None:
    delivery = _delivery()
    agent_section = RuntimePromptSection(
        label="Agent",
        source_kind="agent_system_prompt",
        source_id="reviewer",
        content="Agent-specific prompt",
    )
    with (
        patch(
            "app.api.helpers.agent_preview.build_canonical_context_delivery",
            new=AsyncMock(return_value=delivery),
        ),
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new=AsyncMock(return_value=[agent_section]),
        ),
        patch(
            "app.api.helpers.agent_preview.get_memory_settings",
            new=AsyncMock(return_value=_settings()),
        ),
    ):
        preview = await build_agent_preview(AsyncMock(), _agent(), task_type="chat")

    assert preview["combined_prompt"] == (
        "## Operator\nCanonical policy\n\nAgent-specific prompt"
    )
    assert preview["canonical_context"]["payload_hash"] == delivery.payload_hash
    assert preview["canonical_context"]["block_ids"] == ["prompt:operator"]
    assert [section["source_kind"] for section in preview["sections"]] == [
        "canonical_prompt",
        "agent_system_prompt",
    ]


@pytest.mark.asyncio
async def test_preview_keeps_operator_prompts_when_agent_memory_is_disabled() -> None:
    delivery = _delivery()
    build_delivery = AsyncMock(return_value=delivery)
    config = {
        "injection_enabled": False,
        "project_index_enabled": False,
        "tool_capabilities_enabled": False,
    }
    with (
        patch(
            "app.api.helpers.agent_preview.build_canonical_context_delivery",
            build_delivery,
        ),
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.api.helpers.agent_preview.get_memory_settings",
            new=AsyncMock(return_value=_settings()),
        ),
    ):
        preview = await build_agent_preview(AsyncMock(), _agent(memory_config=config))

    call = build_delivery.await_args
    assert call is not None
    request = call.args[1]
    assert request.include_prompts is True
    assert request.include_memories is False
    assert request.include_project_index is False
    assert request.include_tool_capabilities is False
    assert preview["combined_prompt"] == delivery.rendered


@pytest.mark.asyncio
async def test_preview_task_prompt_remains_user_layer_and_drives_query() -> None:
    delivery = _delivery()
    with (
        patch(
            "app.api.helpers.agent_preview.build_canonical_context_delivery",
            new=AsyncMock(return_value=delivery),
        ) as build_delivery,
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "app.api.helpers.agent_preview.get_memory_settings",
            new=AsyncMock(return_value=_settings()),
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            _agent(),
            task_type="custom",
            prompt_input="Implement canonical context parity",
        )

    assert preview["task_prompt"] == "Implement canonical context parity"
    assert preview["memory_query"] == "Implement canonical context parity"
    assert preview["sections"][-1]["placement"] == "user"
    call = build_delivery.await_args
    assert call is not None
    assert call.args[1].query == "Implement canonical context parity"


def test_preview_budget_telemetry_reports_but_does_not_trim() -> None:
    section = RuntimePromptSection(
        label="Large canonical context",
        source_kind="canonical_mandate",
        source_id="mandate",
        content="policy " * 20_000,
    )

    telemetry = _build_budget_telemetry([section], [])

    assert telemetry["severity"] == "danger"
    assert telemetry["warning_count"] >= 1
    assert telemetry["section_breakdown"][0]["source_id"] == "mandate"
