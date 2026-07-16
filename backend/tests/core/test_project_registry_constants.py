from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.constants.projects import (
    get_known_roots,
    get_valid_project_ids,
    invalidate_project_cache,
    refresh_project_cache,
    validate_project_id,
)


@pytest.mark.asyncio
async def test_project_identity_comes_only_from_st_registry() -> None:
    invalidate_project_cache()
    registry = {
        "agent-hub": "/srv/workspaces/projects/agent-hub",
        "summitflow": "/srv/workspaces/projects/summitflow",
    }
    try:
        with patch(
            "app.core.project_roots.get_registered_project_roots",
            new=AsyncMock(return_value=registry),
        ) as load_registry:
            assert await refresh_project_cache() == frozenset(registry)

        load_registry.assert_awaited_once_with(refresh=True)
        assert get_valid_project_ids() == frozenset(registry)
        assert get_known_roots() == registry
        await validate_project_id("agent-hub")
        with pytest.raises(ValueError, match="Unknown project_id"):
            await validate_project_id("permission-row-only")
    finally:
        invalidate_project_cache()
