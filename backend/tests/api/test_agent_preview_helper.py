from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.api.helpers.agent_preview import build_agent_preview
from app.services.agent_dto import AgentDTO


@pytest.mark.asyncio
async def test_build_agent_preview_uses_runtime_mandate_composition() -> None:
    agent = AgentDTO(
        id=1,
        slug="refactor",
        name="Refactor",
        description=None,
        system_prompt="legacy system prompt",
        primary_model_id="claude-sonnet-4-6",
        fallback_models=[],
        escalation_model_id=None,
        strategies={},
        temperature=0.2,
        thinking_level=None,
        verbosity_level=None,
        is_active=True,
        is_coding_agent=True,
        tool_permissions=None,
        memory_config=None,
        max_concurrency=None,
        max_subagent_concurrency=None,
        daily_token_budget=None,
        hourly_request_limit=None,
        timeout_seconds=None,
        version=1,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    fake_context = type(
        "Ctx",
        (),
        {
            "mandates": [type("M", (), {"uuid": "12345678-aaaa"})()],
            "guardrails": [type("G", (), {"uuid": "87654321-bbbb"})()],
        },
    )()

    with (
        patch(
            "app.api.helpers.agent_preview.collect_runtime_prompt_sections",
            new_callable=AsyncMock,
            return_value=[
                type(
                    "Section",
                    (),
                    {
                        "content": "<platform_context>db prompt</platform_context>",
                        "to_preview_dict": lambda self: {
                            "label": "Platform Context",
                            "source_kind": "global_prompt",
                            "source_id": "platform-context",
                            "role": None,
                            "priority": None,
                            "updated_at": None,
                            "content_hash": "abcd1234",
                            "chars": 44,
                            "estimated_tokens": 11,
                            "content": "<platform_context>db prompt</platform_context>",
                        },
                    },
                )(),
            ],
        ),
        patch(
            "app.api.helpers.agent_preview.join_runtime_prompt_sections",
            return_value="<platform_context>db prompt</platform_context>",
        ),
        patch(
            "app.api.helpers.agent_preview.build_progressive_context",
            new_callable=AsyncMock,
            return_value=fake_context,
        ),
        patch(
            "app.api.helpers.agent_preview.format_progressive_context",
            return_value="## Mandates\n- [M:12345678] keep prompts in db",
        ),
    ):
        preview = await build_agent_preview(
            AsyncMock(),
            agent,
        )

    assert "<platform_context>db prompt</platform_context>" in preview["combined_prompt"]
    assert "## Mandates" in preview["combined_prompt"]
    assert preview["mandate_count"] == 1
    assert preview["guardrail_count"] == 1
    assert preview["mandate_uuids"] == ["12345678"]
    assert preview["guardrail_uuids"] == ["87654321"]
    assert preview["sections"][0]["source_id"] == "platform-context"
