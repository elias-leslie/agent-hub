from __future__ import annotations

import pytest

from app.api.complete.turn_budget import resolve_tool_max_turns


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        (1, 3),
        (3, 3),
        (7, 7),
    ],
)
def test_resolve_tool_max_turns(requested: int, expected: int) -> None:
    assert resolve_tool_max_turns(requested) == expected
