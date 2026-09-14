from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from app.api.complete.complete_orchestrator import _validate_and_resolve, orchestrate_completion
from app.api.complete.schemas import CompletionRequest


def _request(**changes: object) -> CompletionRequest:
    values = {
        "agent_slug": "neri-hunter",
        "project_id": "neri",
        "session_id": "11111111-1111-4111-8111-111111111111",
        "messages": [{"role": "user", "content": '{"state":"selected snapshot"}'}],
        "system_prompt": "Use only selected evidence.",
        "use_memory": False,
        "disable_agent_fallbacks": True,
        "response_format": {"type": "json_object", "schema": {"type": "object"}},
        "native_continuation": {
            "mode": "snapshot",
            "generation": 1,
            "request_id": "request-1",
            "expected_turn": 0,
            "context_version": "evidence-10",
            "role": "hunter",
            "controller_generation": "controller-1",
            "reasoning_effort": "xhigh",
        },
    }
    values.update(changes)
    return CompletionRequest.model_validate(values)


def test_native_contract_requires_delta_hashes_and_fresh_reviewer() -> None:
    with pytest.raises(ValidationError, match="instruction_hash"):
        _request(
            native_continuation={
                "mode": "delta",
                "generation": 1,
                "request_id": "request-2",
                "expected_turn": 1,
                "context_version": "evidence-11",
                "role": "hunter",
                "controller_generation": "controller-1",
            },
            system_prompt=None,
        )


def test_native_contract_requires_caller_session_id() -> None:
    with pytest.raises(ValidationError, match="caller-supplied session_id"):
        _request(session_id=None)


def test_native_contract_requires_fresh_reviewer() -> None:
    with pytest.raises(ValidationError, match="Reviewer native turns"):
        _request(
            native_continuation={
                "mode": "snapshot",
                "generation": 1,
                "request_id": "review-1",
                "expected_turn": 0,
                "context_version": "review-1",
                "role": "reviewer",
                "controller_generation": "reviewer-1",
                "close_after": False,
            }
        )


@pytest.mark.asyncio
async def test_native_evidence_mentions_do_not_override_or_mutate_routing() -> None:
    request = _request(
        messages=[
            {
                "role": "user",
                "content": '{"evidence":"literal @codex/gpt-6-astra must remain evidence"}',
            }
        ]
    )
    http_request = SimpleNamespace(
        state=SimpleNamespace(
            allowed_projects={"neri"}, client_id="neri-client", request_source="neri-lab"
        )
    )
    resolution = (
        "codex/gpt-daybreak-blue-latest",
        "codex",
        None,
        None,
        "neri-hunter",
    )
    with (
        patch(
            "app.api.complete.complete_orchestrator.resolve_agent_and_model",
            new_callable=AsyncMock,
            return_value=resolution,
        ),
        patch(
            "app.api.complete.complete_orchestrator.apply_mention_override"
        ) as mention_override,
        patch(
            "app.api.complete.complete_orchestrator.validate_agent_slug",
            new_callable=AsyncMock,
        ),
        patch("app.api.complete.complete_orchestrator.validate_project_access"),
        patch("app.api.complete.complete_orchestrator.validate_audio_capability"),
    ):
        resolved = await _validate_and_resolve(request, http_request, AsyncMock())

    assert resolved[3:5] == ("codex/gpt-daybreak-blue-latest", "codex")
    assert "@codex/gpt-6-astra" in str(request.messages[0].content)
    mention_override.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_routes_native_before_transcript_reconstruction() -> None:
    request = _request()
    expected = SimpleNamespace(session_id="native-session")
    validate = AsyncMock(
        return_value=(
            "hash",
            "neri-client",
            "neri-lab",
            "codex/gpt-daybreak-blue-latest",
            "codex",
            None,
            None,
            "neri-hunter",
        )
    )
    with (
        patch("app.api.complete.complete_orchestrator._validate_and_resolve", validate),
        patch("app.api.complete.complete_orchestrator._check_quotas", new_callable=AsyncMock),
        patch(
            "app.api.complete.complete_orchestrator._guard_provider_cooldowns",
            new_callable=AsyncMock,
        ),
        patch(
            "app.api.complete.native_continuation.execute_native_continuation",
            new_callable=AsyncMock,
            return_value=expected,
        ) as execute,
        patch(
            "app.api.complete.complete_orchestrator.build_session_and_messages",
            new_callable=AsyncMock,
        ) as rebuild,
    ):
        result = await orchestrate_completion(
            request, SimpleNamespace(state=SimpleNamespace()), False, AsyncMock()
        )

    assert result is expected
    execute.assert_awaited_once()
    rebuild.assert_not_awaited()
