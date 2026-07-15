"""Tests for fail-closed project authorization helpers."""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.access_control_helpers import require_project_access


def _request(
    *,
    client_id: object = "client-1",
    allowed_projects: object = '["agent-hub"]',
    is_internal: bool = False,
) -> Request:
    request = Request({"type": "http", "method": "POST", "path": "/api/test", "headers": []})
    request.state.client_id = client_id
    request.state.allowed_projects = allowed_projects
    request.state.is_internal = is_internal
    return request


def test_project_access_allows_verified_internal_request() -> None:
    require_project_access(
        _request(client_id=None, allowed_projects=None, is_internal=True),
        "agent-hub",
    )


def test_project_access_allows_identified_unrestricted_client() -> None:
    require_project_access(_request(allowed_projects=None), "any-project")


def test_project_access_allows_listed_project() -> None:
    require_project_access(_request(), "agent-hub")


@pytest.mark.parametrize(
    ("allowed_projects", "expected_code"),
    [
        ('["rootfall"]', "project_access_denied"),
        ('{"agent-hub": true}', "project_access_denied"),
        ("not-json", "project_access_denied"),
        (["agent-hub"], "project_access_policy_invalid"),
    ],
)
def test_project_access_denies_unlisted_or_malformed_policy(
    allowed_projects: object,
    expected_code: str,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        require_project_access(
            _request(allowed_projects=allowed_projects),
            "agent-hub",
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == expected_code


def test_project_access_fails_closed_without_identified_state() -> None:
    request = Request(
        {"type": "http", "method": "POST", "path": "/api/test", "headers": []}
    )

    with pytest.raises(HTTPException) as exc_info:
        require_project_access(request, "agent-hub")

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "project_identity_unavailable"
