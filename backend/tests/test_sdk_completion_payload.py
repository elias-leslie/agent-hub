"""Tests for the Agent Hub client payload builder."""

from __future__ import annotations

import sys
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[2] / "packages" / "agent-hub-client"
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))


def _build_completion_payload(*args, **kwargs):
    from agent_hub._completion import build_completion_payload

    return build_completion_payload(*args, **kwargs)


def test_build_completion_payload_includes_false_use_memory_flag() -> None:
    """SDK callers must be able to explicitly disable memory injection."""
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        use_memory=False,
    )

    assert payload["use_memory"] is False


def test_build_completion_payload_includes_true_use_memory_flag() -> None:
    """SDK callers should still be able to opt into memory injection."""
    payload = _build_completion_payload(
        messages=[{"role": "user", "content": "Review AAPL"}],
        project_id="portfolio-ai",
        agent_slug="equity-analyst",
        use_memory=True,
    )

    assert payload["use_memory"] is True
