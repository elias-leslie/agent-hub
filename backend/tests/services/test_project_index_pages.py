"""Startup project index renders pages on one line without repeated labels."""

from __future__ import annotations

import pytest

from app.services.memory import project_index_context as module


def test_pages_render_compact_and_keep_distinct_labels(monkeypatch: pytest.MonkeyPatch) -> None:
    data = {"project": "demo", "pages": ["/ (home)", "/git (git)", "/b/:id/restore/:rid (restore/:rid)", "/x (Dashboard)"]}
    monkeypatch.setattr(module, "_read_project_index", lambda _pid: data)

    rendered = module.format_project_index_context("demo", consumer_profile="agent_startup")

    assert "pages: /, /git, /b/:id/restore/:rid, /x (Dashboard)\n" in rendered
