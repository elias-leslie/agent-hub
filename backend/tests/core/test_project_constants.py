"""Tests for project root cache helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from app.constants import projects


def test_get_known_roots_uses_canonical_root_resolver() -> None:
    projects.invalidate_project_cache()

    with (
        patch.object(projects, "_FALLBACK_PROJECT_IDS", frozenset({"summitflow", "agent-hub"})),
        patch(
            "app.core.project_roots.resolve_project_root",
            side_effect=lambda project_id: Path(f"/resolved/{project_id}"),
        ),
    ):
        roots = projects.get_known_roots()

    assert roots == {
        "summitflow": "/resolved/summitflow",
        "agent-hub": "/resolved/agent-hub",
    }
