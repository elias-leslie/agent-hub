from __future__ import annotations

from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import WebSocket

from app.api import events


def _ws(headers: dict[str, str]) -> WebSocket:
    return cast(WebSocket, SimpleNamespace(headers=headers))


@pytest.fixture(autouse=True)
def _origins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events.settings, "cors_origins", ["https://agent.example.dev"])


@pytest.mark.parametrize(
    "headers",
    [
        {},
        {"origin": "https://agent.example.dev"},
        {"origin": "http://localhost:3003"},
        {"origin": "http://127.0.0.1:9999"},
        {"origin": "http://192.168.1.5:3003", "host": "192.168.1.5:3003"},
    ],
)
def test_events_origin_allowed(headers: dict[str, str]) -> None:
    assert events._origin_allowed(_ws(headers))


def test_events_origin_rejects_cross_site_page() -> None:
    assert not events._origin_allowed(_ws({"origin": "https://evil.example", "host": "localhost:8003"}))
