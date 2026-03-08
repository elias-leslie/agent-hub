from __future__ import annotations

import sys
import types

import pytest

from app.adapters.claude_tools_helpers import _stream_sdk_messages


class ResultMessage:
    pass


@pytest.mark.asyncio
async def test_stream_sdk_messages_drains_after_result_message(monkeypatch: pytest.MonkeyPatch) -> None:
    yielded = []

    async def fake_query(*, prompt, options):
        yielded.append("assistant")
        yield types.SimpleNamespace(content=[], subtype=None)
        yielded.append("result")
        yield ResultMessage()
        yielded.append("after-result")
        yield types.SimpleNamespace(content=[], subtype=None)

    fake_sdk = types.SimpleNamespace(query=fake_query)
    monkeypatch.setitem(sys.modules, "claude_agent_sdk", fake_sdk)

    seen = []
    async for message, session_id in _stream_sdk_messages("prompt", object(), "claude"):
        seen.append((type(message).__name__, session_id))

    assert seen == [("SimpleNamespace", None), ("ResultMessage", None)]
    assert yielded == ["assistant", "result", "after-result"]
