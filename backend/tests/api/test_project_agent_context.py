"""Tests for the read-only project agent-context summary."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.api.project_agent_context import summarize_delivery
from app.middleware.access_control_paths import is_internal_only_path
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    RuntimeContextBlockResponse,
    _RuntimeContextSelection,
    build_canonical_context_delivery,
)

PROJECT = "summitflow"
ROOTS = {PROJECT: "/srv/workspaces/projects/summitflow", "agent-hub": "/srv/workspaces/projects/agent-hub"}
PROJECT_INDEX = "<project-index>\nproject: summitflow\nservices:\n  backend_port: 8001\nurls:\n  frontend: http://localhost:3001\n</project-index>"
SECRET_TEXT = "never-leave-agent-hub"


def _block(source_type: str, source_id: str, title: str, content: str, **extra) -> RuntimeContextBlockResponse:
    return RuntimeContextBlockResponse(
        id=f"{source_type}:{source_id}",
        source_type=source_type,
        source_id=source_id,
        title=title,
        content=content,
        token_count=len(content) // 4,
        origin=extra.pop("origin", "auto"),
        mode="order",
        position=100,
        **extra,
    )


def _selection() -> _RuntimeContextSelection:
    return _RuntimeContextSelection(
        consumer_profile="agent_startup",
        project_id=PROJECT,
        query="startup context",
        blocks=[
            _block("prompt", "safety-directive", "Safety Directive", "Global safety text " + SECRET_TEXT,
                   prompt_type="global_guardrail", scope="global", auto_reason="global scope; always", required=True),
            _block("prompt", "summitflow-policy", "SummitFlow Policy", "Project policy " + SECRET_TEXT,
                   prompt_type="standard", scope="project", scope_id="summitflow", auto_reason="project scope; always"),
            _block("prompt", "other-policy", "Other Policy", "Targets another project too",
                   prompt_type="standard", scope="project", scope_id="neri,summitflow", auto_reason="project scope; always"),
            _block("memory", "mem-project", "Use st check", "Project memory body " + SECRET_TEXT,
                   tier="guardrail", scope="project", scope_id=PROJECT, auto_reason="tier:guardrail",
                   sensitivity_tier="normal"),
            _block("memory", "mem-global", "Shared account", "Global memory body",
                   tier="reference", scope="global", auto_reason="tier:reference", sensitivity_tier="normal"),
            _block("memory", "mem-pinned", "Pinned note", "Pinned memory body",
                   tier="reference", scope="global", origin="override", sensitivity_tier="normal"),
            _block("memory", "mem-private", "Owner home address", "Confidential body " + SECRET_TEXT,
                   tier="reference", scope="project", scope_id=PROJECT, auto_reason="tier:reference",
                   sensitivity_tier="confidential"),
        ],
        excluded=[],
        overrides=[],
        project_index=PROJECT_INDEX,
        tool_capabilities="<tool-capabilities>bash</tool-capabilities>",
        budget_tokens=0,
        budget_enabled=False,
    )


def _patches(selection: _RuntimeContextSelection | None = None):
    select = AsyncMock(return_value=selection or _selection())
    return select, (
        patch("app.core.project_roots.get_registered_project_roots", new=AsyncMock(return_value=ROOTS)),
        patch("app.api.project_agent_context.get_registered_project_roots", new=AsyncMock(return_value=ROOTS)),
        patch("app.services.runtime_context._select_runtime_context", new=select),
        patch("app.services.runtime_context.get_memory_settings",
              new=AsyncMock(return_value=SimpleNamespace(continuity_enabled=False, continuity_max_sessions=3))),
    )


async def _delivery():
    _select, patches = _patches()
    with patches[0], patches[1], patches[2], patches[3]:
        return await build_canonical_context_delivery(
            AsyncMock(),
            CanonicalContextDeliveryRequest(consumer_surface="claude_code", project_id=PROJECT),
        )


@pytest.mark.asyncio
async def test_summary_groups_project_items_and_links_to_agent_hub_editors() -> None:
    summary = summarize_delivery(await _delivery(), project_id=PROJECT)

    assert summary.status == "ok"
    by_id = {item.source_id: item for item in summary.items}
    assert by_id["summitflow-policy"].group == "project"
    assert by_id["summitflow-policy"].edit_path == "/prompts/summitflow-policy"
    assert by_id["summitflow-policy"].reason == "project scope; always"
    assert by_id["other-policy"].group == "project"
    assert by_id["safety-directive"].group == "global"
    assert by_id["safety-directive"].required is True
    assert by_id["mem-project"].group == "project"
    assert by_id["mem-project"].edit_path == "/memory?scope=project"
    assert by_id["mem-project"].reason == "guardrail tier"
    assert by_id["mem-global"].edit_path == "/memory?scope=global"
    assert by_id["mem-pinned"].reason == "pinned in runtime context"

    index = by_id[f"project-index:{PROJECT}"]
    assert (index.kind, index.group, index.edit_path) == ("project_index", "project", None)
    assert index.facts == ["project", "services", "urls"]
    assert index.char_count == len(PROJECT_INDEX)
    tools = next(item for item in summary.items if item.kind == "tool_capabilities")
    assert tools.group == "global"

    assert summary.totals.project_items == 4
    assert summary.totals.items == len(summary.items)
    assert summary.totals.project_tokens + summary.totals.global_tokens + summary.withheld.estimated_tokens \
        == summary.totals.item_tokens
    assert summary.totals.delivered_tokens > 0
    assert summary.manage_path == "/runtime-context"


@pytest.mark.asyncio
async def test_summary_withholds_sensitive_memories_and_never_returns_content() -> None:
    summary = summarize_delivery(await _delivery(), project_id=PROJECT)

    assert "mem-private" not in {item.source_id for item in summary.items}
    assert summary.withheld.count == 1
    assert summary.withheld.estimated_tokens > 0
    body = summary.model_dump_json()
    assert SECRET_TEXT not in body
    assert "Owner home address" not in body


@pytest.mark.asyncio
async def test_summary_redacts_secret_shaped_titles() -> None:
    selection = _selection()
    selection.blocks[3].title = "token sk-ant-" + "a" * 40
    _select, patches = _patches(selection)
    with patches[0], patches[1], patches[2], patches[3]:
        delivery = await build_canonical_context_delivery(
            AsyncMock(), CanonicalContextDeliveryRequest(consumer_surface="claude_code", project_id=PROJECT)
        )

    summary = summarize_delivery(delivery, project_id=PROJECT)
    title = next(item.title for item in summary.items if item.source_id == "mem-project")
    assert "sk-ant-" not in title
    assert "[REDACTED:anthropic_key]" in title


def test_endpoint_delivers_default_coding_agent_startup_context(api_client) -> None:
    select, patches = _patches()
    with patches[0], patches[1], patches[2], patches[3]:
        response = api_client.get(f"/api/projects/{PROJECT}/agent-context")

    assert response.status_code == 200
    body = response.json()
    assert body["project_id"] == PROJECT
    assert body["consumer_surface"] == "claude_code"
    assert body["consumer_profile"] == "agent_startup"
    assert SECRET_TEXT not in response.text
    kwargs = select.await_args.kwargs
    assert kwargs["project_id"] == PROJECT
    assert kwargs["consumer_surface"] == "claude_code"
    assert kwargs["capabilities"] == ["bash"]
    assert kwargs["phase"] == "startup"


def test_endpoint_rejects_unregistered_project(api_client) -> None:
    select, patches = _patches()
    with patches[0], patches[1], patches[2], patches[3]:
        response = api_client.get("/api/projects/not-registered/agent-context")

    assert response.status_code == 404
    select.assert_not_awaited()


def test_endpoint_reports_failed_delivery_without_items(api_client) -> None:
    select, patches = _patches()
    select.side_effect = RuntimeError("memory store unavailable")
    with patches[0], patches[1], patches[2], patches[3]:
        response = api_client.get(f"/api/projects/{PROJECT}/agent-context")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["items"] == []
    assert body["failure"]["error_type"] == "RuntimeError"


def test_summary_route_is_readable_by_identified_clients() -> None:
    # Runtime-context controls stay dashboard-only; this summary must not.
    assert is_internal_only_path("/api/runtime-context/agent_startup/preview")
    assert not is_internal_only_path(f"/api/projects/{PROJECT}/agent-context")
