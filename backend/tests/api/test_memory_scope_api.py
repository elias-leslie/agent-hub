"""Scope-only route authorization and request boundaries."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.services.context_governance import MemoryScopePreviewRequest, _authorize

PAYLOAD = {"memory_id": "12345678", "scope": "project", "scope_id": "learn-o-tron", "reason": "Correct targeting"}
CLIENT = {"id": "internal-1", "status": "active", "client_type": "internal", "allowed_projects": None}


def test_scope_api_requires_internal_secret(test_client):
    with patch("app.middleware.access_control_auth.get_cached_client", new=AsyncMock(return_value=CLIENT)):
        denied = test_client.post("/api/runtime-context/memory-scope/preview", json=PAYLOAD)
    assert denied.status_code == 403
    assert denied.json()["error"] == "internal_only"


def test_scope_api_requires_registered_active_client(api_client):
    missing = api_client.post("/api/runtime-context/memory-scope/preview", json=PAYLOAD)
    assert missing.status_code == 401
    assert "Registered service client" in missing.json().get("detail", repr(missing.json()))

    with patch("app.middleware.access_control_auth.get_cached_client", new=AsyncMock(return_value={**CLIENT, "status": "suspended"})):
        inactive = api_client.post("/api/runtime-context/memory-scope/preview", json=PAYLOAD, headers={"X-Client-Id": CLIENT["id"]})
    assert inactive.status_code == 403


def test_scope_api_transport_uses_registered_client_and_rejects_extra_fields(api_client):
    receipt = {"memory_id": "12345678", "expected_revision": "sha256:before", "before": {"scope": "global", "scope_id": None}, "after": {"scope": "project", "scope_id": "learn-o-tron"}, "content_unchanged": True, "token_delta": 0}
    with (patch("app.middleware.access_control_auth.get_cached_client", new=AsyncMock(return_value=CLIENT)),
          patch("app.api.runtime_context.preview_memory_scope", new=AsyncMock(return_value=receipt)) as preview):
        response = api_client.post("/api/runtime-context/memory-scope/preview", json=PAYLOAD, headers={"X-Client-Id": CLIENT["id"]})
        assert response.status_code == 200
        assert response.json() == receipt
        assert preview.await_args is not None
        assert preview.await_args.args[2] == CLIENT
        invalid = api_client.post("/api/runtime-context/memory-scope/preview", json={**PAYLOAD, "content": "overwrite"}, headers={"X-Client-Id": CLIENT["id"]})
        assert invalid.status_code == 422


@pytest.mark.parametrize(("client", "before", "target", "status"), [
    ({"client_type": "external", "allowed_projects": None}, ("global", None), ("project", "learn-o-tron"), 403),
    ({"client_type": "service", "allowed_projects": '["learn-o-tron"]'}, ("global", None), ("project", "learn-o-tron"), 403),
    ({"client_type": "service", "allowed_projects": '["learn-o-tron"]'}, ("project", "learn-o-tron"), ("project", "other"), 403),
    ({"client_type": "internal", "allowed_projects": '["other"]'}, ("global", None), ("project", "learn-o-tron"), 403),
    ({"client_type": "internal", "allowed_projects": '["learn-o-tron"]'}, ("global", None), ("project", "learn-o-tron"), 403),
    ({"client_type": "internal", "allowed_projects": '["portfolio-ai"]'}, ("project", "portfolio-ai"), ("project", "learn-o-tron"), 403),
    ({"client_type": "internal", "allowed_projects": '["agent-hub", "learn-o-tron"]'}, ("project", "other"), ("project", "learn-o-tron"), 403),
])
def test_scope_client_cannot_cross_its_boundary(client, before, target, status):
    with pytest.raises(HTTPException) as error:
        _authorize(client, *before, *target)
    assert error.value.status_code == status


def test_scope_client_accepts_authorized_transition():
    _authorize(CLIENT, "global", None, "project", "learn-o-tron")
    scoped_internal = {"client_type": "internal", "allowed_projects": '["agent-hub", "learn-o-tron", "other"]'}
    _authorize(scoped_internal, "global", None, "project", "learn-o-tron")
    _authorize(scoped_internal, "project", "other", "project", "learn-o-tron")
    _authorize({"client_type": "service", "allowed_projects": '["learn-o-tron"]'},
               "project", "learn-o-tron", "project", "learn-o-tron")


@pytest.mark.parametrize("changes", [
    {"scope": "global", "scope_id": "learn-o-tron"},
    {"scope": "project", "scope_id": None},
    {"scope": "agent", "scope_id": " "},
    {"reason": " "},
])
def test_scope_request_rejects_mixed_or_missing_fields(changes):
    with pytest.raises(ValueError):
        MemoryScopePreviewRequest.model_validate({**PAYLOAD, **changes})
