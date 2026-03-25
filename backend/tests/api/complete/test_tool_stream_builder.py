from __future__ import annotations

import pytest

from app.adapters.base import Message
from app.api.complete.tool_stream_builder import build_event_stream


def test_build_event_stream_floors_openai_compat_tool_turns(monkeypatch) -> None:
    class Adapter:
        def complete_with_tool_events(self, **kwargs):
            return kwargs

    stream = build_event_stream(
        adapter=Adapter(),
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

    assert stream["max_turns"] == 3
    assert stream["session_id"] == "sess-1"


@pytest.mark.asyncio
async def test_build_event_stream_preserves_claude_tool_turns() -> None:
    class Adapter:
        def complete_with_tool_events(self, **kwargs):
            async def _gen():
                yield kwargs, None

            return _gen()

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
