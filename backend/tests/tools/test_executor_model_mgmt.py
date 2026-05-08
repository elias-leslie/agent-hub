"""Tests for _executor_model_mgmt alias handling."""

from __future__ import annotations

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.tools._executor_model_mgmt import (
    get_agent_details,
    get_model_details,
    update_agent_memory,
    update_agent_model,
)


def _mock_async_session(mock_db: AsyncMock):
    @asynccontextmanager
    async def _session():
        yield mock_db

    return _session


@pytest.mark.anyio
async def test_get_model_details_resolves_explicit_catalog_aliases() -> None:
    mock_db = AsyncMock()

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.model_enrichment_service.get_all_enrichments",
            new_callable=AsyncMock,
            return_value={},
        ),
    ):
        result = await get_model_details("codex-5.2")

    assert "# " in result
    assert "codex/gpt-5.2-codex" in result


@pytest.mark.anyio
async def test_update_agent_model_normalizes_explicit_alias_inputs() -> None:
    mock_db = AsyncMock()
    updated = SimpleNamespace(version=7)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.agent_service.get_agent_service",
        ) as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(
            return_value=SimpleNamespace(
                id="agent-1",
                primary_model_id="codex/gpt-5.4",
                fallback_models=[],
                escalation_model_id=None,
                version=7,
            )
        )
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_model(
            agent_slug="persona",
            primary_model_id="codex-5.2",
            fallback_models=["codex/gpt-5.4", "openai/gpt-5.2"],
            escalation_model_id="claude-sonnet-4-6",
            temperature=None,
            thinking_level=None,
            change_reason="normalize aliases",
        )

    assert "codex/gpt-5.2-codex" in result
    service.update.assert_not_awaited()
    added_routes = [
        call.args[0]
        for call in mock_db.add.call_args_list
        if getattr(call.args[0], "primary_model_id", None) == "codex/gpt-5.2-codex"
    ]
    assert added_routes
    route = added_routes[0]
    assert route.fallback_models == ["codex/gpt-5.4", "openai/gpt-5.2"]
    assert route.escalation_model_id == "claude-sonnet-4-6"


@pytest.mark.anyio
async def test_update_agent_model_normalizes_legacy_prefixed_codex_model_ids() -> None:
    mock_db = AsyncMock()
    updated = SimpleNamespace(version=8)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch(
            "app.services.agent_service.get_agent_service",
        ) as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(
            return_value=SimpleNamespace(
                id="agent-1",
                primary_model_id="codex/gpt-5.4",
                fallback_models=[],
                escalation_model_id=None,
                version=8,
            )
        )
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_model(
            agent_slug="persona",
            primary_model_id="codex/gpt-5.2",
            fallback_models=None,
            escalation_model_id=None,
            temperature=None,
            thinking_level=None,
            change_reason="normalize legacy codex ids",
        )

    assert "primary_model=codex/gpt-5.2-codex" in result
    service.update.assert_not_awaited()
    assert any(
        getattr(call.args[0], "primary_model_id", None) == "codex/gpt-5.2-codex"
        for call in mock_db.add.call_args_list
    )


@pytest.mark.anyio
async def test_get_agent_details_includes_memory_config() -> None:
    mock_db = AsyncMock()
    agent = SimpleNamespace(
        slug="debugger",
        name="Debugger",
        description="Investigates tricky failures.",
        primary_model_id="codex/gpt-5.4",
        fallback_models=["claude-sonnet-4-6"],
        escalation_model_id=None,
        temperature=0.2,
        thinking_level="high",
        is_coding_agent=True,
        is_active=True,
        version=4,
        memory_config={
            "injection_enabled": True,
            "project_index_enabled": True,
            "tool_capabilities_enabled": True,
            "include_mandates": True,
            "include_guardrails": True,
            "include_references": True,
            "reference_index_enabled": True,
            "continuity_enabled": True,
            "continuity_max_sessions": 5,
            "audience_tags": ["debugger-relevant"],
            "exclude_tags": [],
            "exclude_memory_uuids": [],
        },
    )

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch("app.services.agent_service.get_agent_service") as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=agent)

        result = await get_agent_details("debugger")

    assert "Debugger" in result
    assert "debugger-relevant" in result
    assert '"include_references": true' in result


@pytest.mark.anyio
async def test_update_agent_memory_merges_patch_and_tag_operations() -> None:
    mock_db = AsyncMock()
    agent = SimpleNamespace(
        id="agent-1",
        memory_config={
            "include_references": False,
            "audience_tags": ["old-tag"],
            "exclude_tags": ["deprecated"],
        },
    )
    updated = SimpleNamespace(version=9)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch("app.services.agent_service.get_agent_service") as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=agent)
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_memory(
            agent_slug="persona",
            memory_config_patch={
                "include_references": True,
                "query_reference_selection_enabled": True,
                "runtime_consumer_profile": "agent_promptops",
            },
            add_audience_tags=["persona-relevant", "memory-routing"],
            remove_audience_tags=["old-tag"],
            clear_audience_tags=False,
            add_exclude_tags=["archive"],
            remove_exclude_tags=["deprecated"],
            clear_exclude_tags=False,
            change_reason="route project references",
        )

    assert "Agent 'persona' memory updated (version 9)." in result
    await_args = service.update.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["changed_by"] == "persona"
    assert kwargs["memory_config"] == {
        "injection_enabled": True,
        "project_index_enabled": True,
        "tool_capabilities_enabled": True,
        "include_mandates": True,
        "include_guardrails": True,
        "include_references": True,
        "reference_index_enabled": True,
        "continuity_enabled": True,
        "continuity_max_sessions": 5,
        "query_reference_selection_enabled": True,
        "runtime_consumer_profile": "agent_promptops",
        "audience_tags": ["persona-relevant", "memory-routing"],
        "exclude_tags": ["archive"],
        "exclude_memory_uuids": [],
    }


@pytest.mark.anyio
async def test_update_agent_memory_returns_noop_when_patch_is_effectively_empty() -> None:
    mock_db = AsyncMock()
    agent = SimpleNamespace(
        id="agent-1",
        memory_config={"include_references": True, "audience_tags": ["persona-relevant"]},
    )

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch("app.services.agent_service.get_agent_service") as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=agent)
        service.update = AsyncMock()

        result = await update_agent_memory(
            agent_slug="persona",
            memory_config_patch={"include_references": True},
            add_audience_tags=["persona-relevant"],
            remove_audience_tags=None,
            clear_audience_tags=False,
            add_exclude_tags=None,
            remove_exclude_tags=None,
            clear_exclude_tags=False,
            change_reason="no actual change",
        )

    assert "No memory config changes required" in result
    service.update.assert_not_awaited()


@pytest.mark.anyio
async def test_update_agent_memory_canonicalizes_disabled_injection_state() -> None:
    mock_db = AsyncMock()
    agent = SimpleNamespace(
        id="agent-1",
        memory_config={
            "injection_enabled": True,
            "project_index_enabled": True,
            "tool_capabilities_enabled": True,
            "include_mandates": True,
            "include_guardrails": True,
            "include_references": True,
            "reference_index_enabled": True,
            "continuity_enabled": True,
            "continuity_max_sessions": 5,
            "audience_tags": [],
            "exclude_tags": [],
            "exclude_memory_uuids": [],
        },
    )
    updated = SimpleNamespace(version=10)

    with (
        patch("app.db.async_session", _mock_async_session(mock_db)),
        patch("app.services.agent_service.get_agent_service") as mock_get_service,
    ):
        service = mock_get_service.return_value
        service.get_by_slug = AsyncMock(return_value=agent)
        service.update = AsyncMock(return_value=updated)

        result = await update_agent_memory(
            agent_slug="git-agent",
            memory_config_patch={"injection_enabled": False},
            add_audience_tags=None,
            remove_audience_tags=None,
            clear_audience_tags=False,
            add_exclude_tags=None,
            remove_exclude_tags=None,
            clear_exclude_tags=False,
            change_reason="disable helper-agent memory",
        )

    assert "Agent 'git-agent' memory updated (version 10)." in result
    await_args = service.update.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["memory_config"] == {
        "injection_enabled": False,
        "project_index_enabled": True,
        "tool_capabilities_enabled": True,
        "include_mandates": False,
        "include_guardrails": False,
        "include_references": False,
        "reference_index_enabled": False,
        "continuity_enabled": False,
        "continuity_max_sessions": 5,
        "audience_tags": [],
        "exclude_tags": [],
        "exclude_memory_uuids": [],
    }
