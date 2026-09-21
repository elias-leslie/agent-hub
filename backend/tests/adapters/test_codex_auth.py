"""Secret-safe Codex OAuth refresh error handling."""

from __future__ import annotations

import logging

import httpx
import pytest

from app.adapters import codex_auth
from app.adapters.codex_auth import CodexAuthError


class _Client:
    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, _exc_type, _exc, _tb) -> None:
        return None

    async def post(self, *_args, **_kwargs) -> httpx.Response:
        return httpx.Response(
            401,
            json={"error": {"code": "private-provider-detail"}},
        )


@pytest.mark.asyncio
async def test_unknown_refresh_error_is_sanitized(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(codex_auth.httpx, "AsyncClient", _Client)

    with (
        caplog.at_level(logging.ERROR, logger=codex_auth.__name__),
        pytest.raises(CodexAuthError, match="code=unknown") as exc_info,
    ):
        await codex_auth.refresh_access_token("private-refresh-token")

    combined = f"{exc_info.value}\n{caplog.text}"
    assert "private-provider-detail" not in combined
    assert "private-refresh-token" not in combined
