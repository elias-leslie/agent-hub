from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.api.agents import _agent_create_kwargs, _agent_update_kwargs
from app.api.endpoints import subagent as subagent_endpoint
from app.api.orchestration_models import SubagentRequest
from app.api.schemas.agent_schemas import AgentCreateRequest, AgentUpdateRequest
from app.constants.models import CLAUDE_SONNET
from app.services.agent_crud import apply_agent_updates
from app.services.orchestration.subagent_executor import _call_adapter
from app.services.orchestration.subagent_models import SubagentConfig


def _make_agent_create_request(**overrides) -> AgentCreateRequest:
    payload = {
        "slug": "timeout-agent",
        "name": "Timeout Agent",
        "system_prompt": "You handle long-running work.",
        "primary_model_id": CLAUDE_SONNET,
    }
    payload.update(overrides)
    return AgentCreateRequest.model_validate(payload)


class _FakeAdapter:
    def __init__(self, result) -> None:
        self.complete = AsyncMock(return_value=result)


@pytest.mark.parametrize(
    ("agent_request", "expected"),
    [
        (_make_agent_create_request(), None),
        (_make_agent_create_request(timeout_seconds=None), None),
        (_make_agent_create_request(timeout_seconds=7201), 7201),
    ],
)
def test_agent_create_timeout_values_round_trip(agent_request: AgentCreateRequest, expected: float | None) -> None:
    assert _agent_create_kwargs(agent_request, auth=None)["timeout_seconds"] == expected


def test_agent_create_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValidationError):
        _make_agent_create_request(timeout_seconds=0)


@pytest.mark.parametrize(
    ("update_request", "expected"),
    [
        (AgentUpdateRequest(), None),
        (AgentUpdateRequest.model_validate({"timeout_seconds": None}), None),
        (AgentUpdateRequest.model_validate({"timeout_seconds": 7201}), 7201),
    ],
)
def test_agent_update_timeout_values_round_trip(update_request: AgentUpdateRequest, expected: float | None) -> None:
    assert _agent_update_kwargs(update_request, auth=None)["timeout_seconds"] == expected


def test_agent_update_non_positive_timeout_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentUpdateRequest.model_validate({"timeout_seconds": 0})


def test_apply_agent_updates_preserves_existing_timeout_for_none() -> None:
    agent = SimpleNamespace(timeout_seconds=90.0)

    apply_agent_updates(agent, timeout_seconds=None)

    assert agent.timeout_seconds == 90.0


@pytest.mark.parametrize(
    ("subagent_request", "expected"),
    [
        (
            SubagentRequest.model_validate(
                {
                    "task": "Audit files",
                    "name": "timeout-canary",
                    "provider": "claude",
                    "project_id": "summitflow",
                }
            ),
            None,
        ),
        (
            SubagentRequest.model_validate(
                {
                    "task": "Audit files",
                    "name": "timeout-canary",
                    "provider": "claude",
                    "project_id": "summitflow",
                    "timeout_seconds": None,
                }
            ),
            None,
        ),
        (
            SubagentRequest.model_validate(
                {
                    "task": "Audit files",
                    "name": "timeout-canary",
                    "provider": "claude",
                    "project_id": "summitflow",
                    "timeout_seconds": 7201,
                }
            ),
            7201,
        ),
    ],
)
@pytest.mark.asyncio
async def test_subagent_endpoint_passes_timeout_seconds_through(subagent_request: SubagentRequest, expected: float | None) -> None:
    fake_result = SimpleNamespace(
        subagent_id="abc123",
        name=subagent_request.name,
        content="ok",
        status="completed",
        provider=subagent_request.provider,
        model="claude-sonnet",
        input_tokens=1,
        output_tokens=1,
        thinking_content=None,
        thinking_tokens=None,
        error=None,
        trace_id="trace-1",
    )
    fake_manager = SimpleNamespace(spawn=AsyncMock(return_value=fake_result))

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(subagent_endpoint, "get_subagent_manager", lambda: fake_manager)
        mp.setattr(subagent_endpoint, "get_current_trace_id", lambda: "trace-1")
        await subagent_endpoint.spawn_subagent(subagent_request)

    spawn_kwargs = fake_manager.spawn.await_args.kwargs
    assert spawn_kwargs["config"].timeout_seconds == expected


@pytest.mark.asyncio
async def test_call_adapter_skips_wait_for_when_timeout_is_none() -> None:
    adapter = _FakeAdapter(SimpleNamespace(content="ok", provider="claude", model="model", input_tokens=1, output_tokens=1, thinking_content=None, thinking_tokens=None))
    config = SubagentConfig(name="test", timeout_seconds=None)

    with pytest.MonkeyPatch.context() as mp:
        wait_for = AsyncMock(side_effect=AssertionError("wait_for should not be used"))
        mp.setattr(asyncio, "wait_for", wait_for)
        result = await _call_adapter(adapter, [], "model", config)

    assert result.content == "ok"
    wait_for.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_adapter_uses_wait_for_for_positive_timeout() -> None:
    adapter = _FakeAdapter(SimpleNamespace(content="ok", provider="claude", model="model", input_tokens=1, output_tokens=1, thinking_content=None, thinking_tokens=None))
    config = SubagentConfig(name="test", timeout_seconds=12)

    async def fake_wait_for(coro, timeout):
        assert timeout == 12
        return await coro

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(asyncio, "wait_for", fake_wait_for)
        result = await _call_adapter(adapter, [], "model", config)

    assert result.content == "ok"
