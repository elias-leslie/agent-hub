"""Tests for project root cache helpers."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.constants import projects


@pytest.mark.asyncio
async def test_get_known_roots_uses_canonical_st_registry() -> None:
    projects.invalidate_project_cache()
    registry = {
        "summitflow": "/resolved/summitflow",
        "agent-hub": "/resolved/agent-hub",
    }
    with patch(
        "app.core.project_roots.get_registered_project_roots",
        new=AsyncMock(return_value=registry),
    ):
        await projects.refresh_project_cache()
        roots = projects.get_known_roots()

    assert roots == registry
    projects.invalidate_project_cache()
