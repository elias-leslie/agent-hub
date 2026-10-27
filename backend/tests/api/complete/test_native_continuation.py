from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.complete.complete_orchestrator import _validate_and_resolve, orchestrate_completion
from app.api.complete.native_continuation import (
    _cyber_access_program,
    _payload_hash,
    execute_native_continuation,
)
from app.api.complete.schemas import CompletionRequest

NERI_PAYLOAD_CONTRACT_HASH = "2c6ad1d8636d7653b26d0d1783868eafdebfff37106b83e9032b4bbe2ef88a0f"


def _request(**changes: object) -> CompletionRequest:
    values = {
        "agent_slug": "neri-hunter",
        "project_id": "neri-hunters",
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
    with pytest.raises(ValidationError, match="Reporter and reviewer native turns"):
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


def test_native_contract_accepts_fresh_reporter_snapshot() -> None:
    request = _request(
        agent_slug="neri-reporter",
        native_continuation={
            "mode": "snapshot",
            "generation": 1,
            "request_id": "report-1",
            "expected_turn": 0,
            "context_version": "source-unit-1",
            "role": "reporter",
            "controller_generation": "reporter-1",
            "close_after": True,
        },
    )

    assert request.native_continuation is not None
    assert request.native_continuation.role == "reporter"


def test_native_contract_rejects_retained_reporter_delta() -> None:
    with pytest.raises(ValidationError, match="Reporter and reviewer native turns"):
        _request(
            agent_slug="neri-reporter",
            system_prompt=None,
            native_continuation={
                "mode": "delta",
                "generation": 1,
                "request_id": "report-2",
                "expected_turn": 1,
                "context_version": "source-unit-2",
                "role": "reporter",
                "controller_generation": "reporter-1",
                "instruction_hash": "a" * 64,
                "tool_policy_hash": "b" * 64,
                "close_after": True,
            },
        )


def test_neri_reporter_payload_contract_vector() -> None:
    packet = {"source_unit": {"digest": "a" * 64}}
    output_schema = {
        "type": "object",
        "properties": {"status": {"type": "string"}},
        "required": ["status"],
        "additionalProperties": False,
    }
    request = _request(
        agent_slug="neri-reporter",
        messages=[{
            "role": "user",
            "content": json.dumps(packet, sort_keys=True, separators=(",", ":")),
        }],
        system_prompt="Apply the Neri vector contract.",
        response_format={"type": "json_object", "schema": output_schema},
        native_continuation={
            "mode": "snapshot",
            "generation": 1,
            "request_id": "report-vector-1",
            "expected_turn": 0,
            "context_version": "source-vector-1",
            "role": "reporter",
            "controller_generation": "reporter-vector-1",
            "reasoning_effort": "high",
            "close_after": True,
        },
    )

    assert _payload_hash(request, "codex/gpt-6-astra") == (
        NERI_PAYLOAD_CONTRACT_HASH
    )


@pytest.mark.asyncio
async def test_native_roles_belong_to_neri_hunters_not_coordination() -> None:
    db = AsyncMock()
    with pytest.raises(HTTPException, match="Neri Hunters inference roles"):
        await execute_native_continuation(
            _request(project_id="neri"),
            provider="codex",
            resolved_model="codex/gpt-5.6-sol-daybreak-blue",
            resolved_agent=None,
            mandate=None,
            agent_used="neri-hunter",
            db=db,
            client_id="neri-client",
            request_source="neri-lab",
        )
    db.execute.assert_not_called()


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
            allowed_projects={"neri-hunters"}, client_id="neri-client", request_source="neri-lab"
        )
    )
    resolution = (
        "codex/gpt-5.6-sol-daybreak-blue",
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

    assert resolved[3:5] == ("codex/gpt-5.6-sol-daybreak-blue", "codex")
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
            "codex/gpt-5.6-sol-daybreak-blue",
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


def test_cyber_access_program_defaults_to_the_catalog_requirement() -> None:
    assert _cyber_access_program(None, "codex/gpt-5.6-sol-daybreak-blue") == "daybreakBlue"
    assert _cyber_access_program(None, "codex/gpt-6.1-sol") is None
    assert _cyber_access_program("standard", "codex/gpt-6.1-sol") == "standard"
