from __future__ import annotations

from unittest.mock import sentinel

import pytest

from app.adapters.base import Message
from app.api.complete.tool_stream_builder import build_event_stream


def test_build_event_stream_floors_openai_compat_tool_turns(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_adapt_openai_stream(*args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return sentinel.stream

    monkeypatch.setattr(
        "app.api.complete.openai_event_adapter.adapt_openai_stream",
        fake_adapt_openai_stream,
    )

    stream = build_event_stream(
        adapter=sentinel.adapter,
        messages=[Message(role="user", content="hi")],
        provider="codex",
        model="codex/gpt-5.4",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        permission_config=None,
        max_turns=1,
        project_id="agent-hub",
        session_id="sess-1",
        agent_slug="memory-curator",
    )

    assert stream is sentinel.stream
    assert captured["args"][6] == 20


@pytest.mark.asyncio
async def test_build_event_stream_preserves_claude_tool_turns(monkeypatch) -> None:
    class Adapter:
        def complete_with_tools(self, **kwargs):
            async def _gen():
                yield kwargs, None

            return _gen()

    monkeypatch.setattr(
        "app.api.complete.claude_event_adapter.adapt_claude_stream",
        lambda raw_stream: raw_stream,
    )

    stream = build_event_stream(
        adapter=Adapter(),
        messages=[Message(role="user", content="hi")],
        provider="claude",
        model="claude-sonnet-4-6",
        tools=[],
        tool_catalog=None,
        working_dir=None,
        permission_config=None,
        max_turns=7,
        project_id="agent-hub",
        session_id="sess-2",
        agent_slug="debugger",
    )

    item, _ = await anext(stream)
    assert item["max_turns"] == 7
