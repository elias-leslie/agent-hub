from __future__ import annotations

import pytest

from app.api.complete.orchestrator import completion_options


@pytest.mark.parametrize(
    ("stored", "expected"),
    [(None, None), ("none", None), ("minimal", "minimal"), ("high", "high"), ("ultrathink", "xhigh")],
)
def test_agent_thinking_levels_map_to_reasoning(stored: str | None, expected: str | None) -> None:
    assert completion_options(0.7, stored).reasoning == expected


def test_unknown_thinking_level_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unsupported thinking level"):
        completion_options(0.7, "turbo")
