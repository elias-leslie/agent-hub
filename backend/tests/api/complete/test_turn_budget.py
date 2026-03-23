from __future__ import annotations

import pytest

from app.api.complete.multi_turn_helpers import TurnLoopConfig
from app.api.complete.turn_budget import resolve_tool_max_turns


@pytest.mark.parametrize(
    ("provider", "requested", "expected"),
    [
        ("claude", 1, 3),
        ("codex", 1, 3),
        ("openai", 7, 7),
        ("gemini", 1, 3),
        ("unknown", 9, 9),
    ],
)
def test_resolve_tool_max_turns(provider: str, requested: int, expected: int) -> None:
    assert resolve_tool_max_turns(provider, requested) == expected


def test_turn_loop_config_uses_proportional_grace_without_low_cap() -> None:
    cfg = TurnLoopConfig(
        adapter=None,
        model="claude-sonnet-4-6",
        provider="claude",
        temperature=0.2,
        max_turns=500,
        enable_caching=False,
        cache_ttl="ephemeral",
        thinking_level=None,
        tools=None,
        enable_programmatic_tools=False,
        response_format=None,
        working_dir=None,
        db=None,
        session_id="sess-1",
        user_messages_for_db=None,
        skip_cache=True,
        cache=None,
        loaded_memory_uuids=[],
        memory_group_id=None,
        progress_callback=None,
        agent_slug=None,
    )

    assert cfg.soft_limit == 250
    assert cfg.wrapup_turn == 500
    assert cfg.hard_cap == 550
