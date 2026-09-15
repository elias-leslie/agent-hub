"""Access-control tests for the project-scoped Neri local-worker routes."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException, Request

from app.api import neri_local_worker as api
from app.services.neri_local_worker import NeriLocalWorkerError


def _request(
    *,
    client_id: str | None = "client-1",
    allowed_projects: object = '["security-research"]',
    internal: bool = False,
    include_policy: bool = True,
) -> Request:
    request = Request({"type": "http", "method": "GET", "path": "/"})
    request.state.is_internal = internal
    if client_id is not None:
        request.state.client_id = client_id
    if include_policy:
        request.state.allowed_projects = allowed_projects
    return request


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_request",
    [
        _request(client_id=None, include_policy=False),
        _request(allowed_projects=["security-research"]),
        _request(allowed_projects='["another-project"]'),
    ],
    ids=["missing-identity", "malformed-policy", "denied-project"],
)
async def test_status_fails_closed_for_unauthorized_identity(http_request: Request) -> None:
    with (
        patch.object(api, "get_neri_local_worker_status", new=AsyncMock()) as worker_status,
        pytest.raises(HTTPException) as raised,
    ):
        await api.status(http_request)

    assert raised.value.status_code == 403
    worker_status.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "http_request",
    [_request(), _request(client_id=None, include_policy=False, internal=True)],
    ids=["allowed-client", "verified-internal"],
)
async def test_status_allows_authorized_identity(http_request: Request) -> None:
    expected = SimpleNamespace(model_id="candidate")
    with patch.object(
        api, "get_neri_local_worker_status", new=AsyncMock(return_value=expected)
    ):
        assert await api.status(http_request) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize("route", ["evaluate", "benchmark"])
async def test_mutating_routes_check_project_access_before_work(route: str) -> None:
    request = _request(allowed_projects='["another-project"]')
    handler = getattr(api, route)
    payload = SimpleNamespace()
    with pytest.raises(HTTPException) as raised:
        await handler(payload, request, AsyncMock())
    assert raised.value.status_code == 403


@pytest.mark.asyncio
async def test_evaluate_returns_sanitized_structured_failure_receipt() -> None:
    failure = NeriLocalWorkerError(
        "provider response included private target material",
        failure_kind="schema",
        runtime_metrics={"input_tokens": 42},
        effective_model="local-model",
        schema_valid=False,
        tool_policy_met=True,
        artifact_identity={
            "artifact_sha256": "a" * 64,
            "private_path": "/private/model/path",
        },
        input_sha256="b" * 64,
        prompt_revision=7,
        evaluation_config={"arm": "role_checklist"},
        partial_content="private partial",
        failed_content="private invalid output",
        pass_evidence=[{
            "pass_number": 1,
            "validated": False,
            "failure_kind": "schema",
            "content": "private invalid output",
            "content_sha256": "c" * 64,
            "runtime_metrics": {"output_tokens": 3},
        }],
    )
    with (
        patch.object(api, "execute_neri_local_worker", new=AsyncMock(side_effect=failure)),
        pytest.raises(HTTPException) as raised,
    ):
        await api.evaluate(SimpleNamespace(), _request(), AsyncMock())

    assert raised.value.status_code == 502
    detail = raised.value.detail
    receipt = detail["details"]["failure_receipt"]
    assert receipt["contract_version"] == "neri-failure-receipt-v1"
    assert receipt["failure_kind"] == "schema"
    assert receipt["failed_content_length"] == len("private invalid output")
    assert receipt["pass_evidence"][0]["content_length"] == len("private invalid output")
    assert receipt["pass_evidence"][0]["content_sha256"] != "c" * 64
    assert receipt["artifact_identity"] == {"artifact_sha256": "a" * 64}
    assert "private_path" not in str(receipt)
    assert "private" not in str(detail)
    assert str(failure) not in str(detail)


@pytest.mark.asyncio
async def test_evaluate_preserves_bounded_tool_policy_failure_evidence() -> None:
    failure = NeriLocalWorkerError(
        "tool output that must not cross the interface",
        failure_kind="tool_policy",
        runtime_metrics={
            "tool_calls_count": 1,
            "used_tool_names": ["bash"],
            "provider_private_detail": "do not retain",
        },
        safety_failures=["unexpected_tool_call"],
        tool_policy_met=False,
    )
    with (
        patch.object(api, "execute_neri_local_worker", new=AsyncMock(side_effect=failure)),
        pytest.raises(HTTPException) as raised,
    ):
        await api.evaluate(SimpleNamespace(), _request(), AsyncMock())

    receipt = raised.value.detail["details"]["failure_receipt"]
    assert receipt["runtime_metrics"] == {
        "tool_calls_count": 1,
        "used_tool_names": ["bash"],
    }
    assert receipt["safety_failures"] == ["unexpected_tool_call"]
    assert "provider_private_detail" not in str(receipt)
