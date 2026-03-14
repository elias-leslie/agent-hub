from __future__ import annotations

import pytest

from app.api.complete.turn_budget import resolve_tool_max_turns


@pytest.mark.parametrize(
    ("provider", "requested", "expected"),
    [
        ("claude", 1, 1),
        ("codex", 1, 20),
        ("openai", 7, 20),
        ("gemini", 1, 5),
        ("unknown", 9, 9),
    ],
)
def test_resolve_tool_max_turns(provider: str, requested: int, expected: int) -> None:
    assert resolve_tool_max_turns(provider, requested) == expected
