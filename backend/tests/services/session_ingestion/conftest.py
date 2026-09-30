"""Isolate native project registry assertions from other tests' cached registries."""

import time

import pytest

from app.constants import projects


@pytest.fixture(autouse=True)
def native_project_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    roots = {
        "agent-hub": "/srv/workspaces/projects/agent-hub",
        "neri": "/srv/workspaces/projects/neri",
    }
    monkeypatch.setattr(projects, "_cached_project_ids", frozenset(roots))
    monkeypatch.setattr(projects, "_cached_roots", roots)
    monkeypatch.setattr(projects, "_cache_timestamp", time.monotonic())
