"""Tests for runtime context APIs."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.runtime_context import (
    RuntimeContextBlockResponse,
    RuntimeContextOverrideResponse,
    RuntimeContextPreviewResponse,
    _render_blocks,
    _resolve_overrides,
)


def _override(**overrides):
    row = SimpleNamespace(
        id="override-1",
        consumer_profile="codex_startup",
        project_id=None,
        source_type="memory",
        source_id="memory-1",
        mode="order",
        position=50,
        enabled=True,
        note=None,
    )
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_resolve_overrides_prefers_project_layer_over_global() -> None:
    rows = [
        _override(id="project", project_id="summitflow", source_id="mem-1", position=90),
        _override(id="global", project_id=None, source_id="mem-1", position=10),
    ]

    resolved = _resolve_overrides(rows)

    assert len(resolved) == 1
    assert resolved[0].id == "project"
    assert resolved[0].position == 90


def test_render_blocks_groups_memory_lines() -> None:
    rendered = _render_blocks(
        [
            RuntimeContextBlockResponse(
                id="prompt:agentic-cli-startup-core",
                source_type="prompt",
                source_id="agentic-cli-startup-core",
                title="Agentic CLI Startup Core",
                content="Direct concise.",
                token_count=2,
                origin="override",
                mode="include",
                position=10,
            ),
            RuntimeContextBlockResponse(
                id="memory:12345678-aaaa-bbbb-cccc-123456789abc",
                source_type="memory",
                source_id="12345678-aaaa-bbbb-cccc-123456789abc",
                title="Use st",
                content="**Use st**: Use st for dev work.",
                token_count=8,
                origin="auto",
                mode="order",
                position=100,
                tier="mandate",
            ),
        ]
    )

    assert "## Agentic CLI Startup Core\nDirect concise." in rendered
    assert "## Runtime Memory" in rendered
    assert "[M:12345678] **Use st**: Use st for dev work." in rendered


@pytest.mark.asyncio
async def test_profiles_endpoint_lists_agentic_cli_profiles(api_client) -> None:
    response = api_client.get("/api/runtime-context/profiles")

    assert response.status_code == 200
    profiles = [item["consumer_profile"] for item in response.json()["profiles"]]
    assert "codex_startup" in profiles
    assert "claude_session_start" in profiles
    assert "gemini_startup" in profiles


@pytest.mark.asyncio
async def test_overrides_endpoint_returns_layer_specific_rows(api_client) -> None:
    override = RuntimeContextOverrideResponse(
        id="override-1",
        consumer_profile="codex_startup",
        project_id="summitflow",
        source_type="memory",
        source_id="memory-1",
        mode="exclude",
        position=20,
        enabled=True,
        note=None,
    )
    mock_list = AsyncMock(return_value=[override])

    with patch("app.api.runtime_context.list_runtime_context_overrides", mock_list):
        response = api_client.get(
            "/api/runtime-context/codex_startup/overrides?project_id=summitflow"
        )

    assert response.status_code == 200
    assert response.json()["overrides"][0]["mode"] == "exclude"
    mock_list.assert_awaited_once()
    await_args = mock_list.await_args
    assert await_args is not None
    assert await_args.kwargs["project_id"] == "summitflow"


@pytest.mark.asyncio
async def test_preview_endpoint_returns_rendered_context(api_client) -> None:
    preview = RuntimeContextPreviewResponse(
        consumer_profile="codex_startup",
        project_id="summitflow",
        query="startup context",
        total_tokens=12,
        rendered="## Agentic CLI Startup Core\nDirect concise.",
        blocks=[
            RuntimeContextBlockResponse(
                id="prompt:agentic-cli-startup-core",
                source_type="prompt",
                source_id="agentic-cli-startup-core",
                title="Agentic CLI Startup Core",
                content="Direct concise.",
                token_count=2,
                origin="override",
                mode="include",
                position=10,
            )
        ],
        overrides=[],
    )
    mock_render = AsyncMock(return_value=preview)

    with patch("app.api.runtime_context.render_runtime_context", mock_render):
        response = api_client.get(
            "/api/runtime-context/codex_startup/preview?project_id=summitflow"
        )

    assert response.status_code == 200
    assert response.json()["total_tokens"] == 12
    assert response.json()["blocks"][0]["source_id"] == "agentic-cli-startup-core"
    mock_render.assert_awaited_once()
