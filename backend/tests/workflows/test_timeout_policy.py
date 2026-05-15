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
from app.constants.models import GEMINI_FLASH, KIMI_CODE_FOR_CODING
from app.services.agent_crud import apply_agent_updates
from app.services.orchestration.subagent_executor import _call_pipeline
from app.services.orchestration.subagent_models import SubagentConfig


def _make_agent_create_request(**overrides) -> AgentCreateRequest:
    payload = {
        "slug": "timeout-agent",
        "name": "Timeout Agent",
        "system_prompt": "You handle long-running work.",
        "primary_model_id": KIMI_CODE_FOR_CODING,
    }
    payload.update(overrides)
    return AgentCreateRequest.model_validate(payload)


def _make_completion_result():
    return SimpleNamespace(
        content="ok",
        provider="gemini",
        model="model",
        input_tokens=1,
        output_tokens=1,
        thinking_content=None,
        thinking_tokens=None,
    )


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
                    "provider": "gemini",
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
                    "provider": "gemini",
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
                    "provider": "gemini",
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
        model=GEMINI_FLASH,
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
async def test_call_pipeline_does_not_wrap_uncapped_subagent_calls() -> None:
    config = SubagentConfig(name="test", timeout_seconds=None)
    fake_complete = AsyncMock(return_value=_make_completion_result())

    with pytest.MonkeyPatch.context() as mp:
        import app.api.complete.core as core_mod

        mp.setattr(core_mod, "complete_internal", fake_complete)
        wait_for = AsyncMock(side_effect=AssertionError("wait_for should not be used"))
        mp.setattr(asyncio, "wait_for", wait_for)
        result = await _call_pipeline([], GEMINI_FLASH, "gemini", config)

    assert result.content == "ok"
    wait_for.assert_not_awaited()


@pytest.mark.asyncio
async def test_call_pipeline_treats_timeout_seconds_as_metadata_only() -> None:
    config = SubagentConfig(name="test", timeout_seconds=12)
    fake_complete = AsyncMock(return_value=_make_completion_result())

    with pytest.MonkeyPatch.context() as mp:
        import app.api.complete.core as core_mod

        mp.setattr(core_mod, "complete_internal", fake_complete)
        wait_for = AsyncMock(side_effect=AssertionError("wait_for should not be used"))
        mp.setattr(asyncio, "wait_for", wait_for)
        result = await _call_pipeline([], GEMINI_FLASH, "gemini", config)

    assert result.content == "ok"
    wait_for.assert_not_awaited()
