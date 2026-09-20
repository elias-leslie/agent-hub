"""Deterministic terminal policy for captured owner-CLI output."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def deterministic_cli_output(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep semantic CLI assertions independent of the runner's color policy."""
    monkeypatch.delenv("CLICOLOR_FORCE", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("TERM", "dumb")
