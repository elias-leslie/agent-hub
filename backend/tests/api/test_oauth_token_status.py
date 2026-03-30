"""Tests for OAuth token storage helpers and status checks."""

from __future__ import annotations

import base64
import json
import time
from unittest.mock import AsyncMock

import pytest

from app.adapters.codex_auth import CodexCredentials
from app.api.oauth_exchange import exchange_codex
from app.api.oauth_schemas import OAuthExchangeRequest
from app.api.oauth_status import check_codex_token_status


def _build_codex_jwt(*, account_id: str = "acct", expires_at: float | None = None) -> str:
    header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=").decode()
    payload = {
        "https://api.openai.com/auth": {"chatgpt_account_id": account_id},
    }
    if expires_at is not None:
        payload["exp"] = int(expires_at)
    payload_part = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    return f"{header}.{payload_part}.sig"


class _FakeCredentialManager:
    def __init__(self, oauth_token: str | None, refresh_token: str | None) -> None:
        self.values = {
            "codex:oauth_token": oauth_token,
            "codex:refresh_token": refresh_token,
        }

    def get(self, provider: str, credential_type: str) -> str | None:
        return self.values.get(f"{provider}:{credential_type}")


@pytest.mark.asyncio
async def test_exchange_codex_stores_structured_token(monkeypatch: pytest.MonkeyPatch) -> None:
    creds = CodexCredentials(
        access_token=_build_codex_jwt(expires_at=time.time() + 3600),
        refresh_token="refresh-token",
        account_id="acct",
        expires_at=1_234_567_890.0,
    )
    upsert = AsyncMock()

    monkeypatch.setattr("app.api.oauth_exchange.exchange_codex_code", AsyncMock(return_value=creds))
    monkeypatch.setattr("app.api.oauth_exchange.upsert_credential", upsert)

    result = await exchange_codex(
        OAuthExchangeRequest(code_input="test-code", state="state"),
        "verifier",
        AsyncMock(),
    )

    assert result is None
    oauth_value = upsert.await_args_list[0].args[3]
    assert json.loads(oauth_value) == {
        "access_token": creds.access_token,
        "expires_at": creds.expires_at,
    }
    assert upsert.await_args_list[1].args[1:] == ("codex", "refresh_token", "refresh-token")


def test_check_codex_token_status_marks_expired_legacy_jwt_without_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cm = _FakeCredentialManager(_build_codex_jwt(expires_at=time.time() - 300), None)

    monkeypatch.setattr("app.api.oauth_status.get_credential_manager", lambda: cm)

    assert check_codex_token_status() == ("expired", None)
