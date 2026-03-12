from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.services.memory._repo_crud import CrudRepository


@pytest.mark.asyncio
async def test_get_revision_resolves_short_revision_prefix_before_lookup() -> None:
    repo = CrudRepository()
    mock_db = AsyncMock()
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = {"id": "full-revision-id"}
    mock_db.execute.return_value = mock_result
    repo.resolve_revision_id_prefix = AsyncMock(return_value="12345678-1234-1234-1234-123456789abc")  # type: ignore[method-assign]

    revision = await repo.get_revision(
        "39dfbfce-1c7b-44b6-9a62-08b0b806e241",
        "12345678",
        db=mock_db,
    )

    assert revision == {"id": "full-revision-id"}
    repo.resolve_revision_id_prefix.assert_awaited_once_with(
        "39dfbfce-1c7b-44b6-9a62-08b0b806e241",
        "12345678",
        db=mock_db,
    )
    mock_db.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_revision_skips_prefix_resolution_for_full_uuid() -> None:
    repo = CrudRepository()
    mock_db = AsyncMock()
    mock_result = Mock()
    mock_result.scalar_one_or_none.return_value = {"id": "full-revision-id"}
    mock_db.execute.return_value = mock_result
    repo.resolve_revision_id_prefix = AsyncMock()  # type: ignore[method-assign]

    revision = await repo.get_revision(
        "39dfbfce-1c7b-44b6-9a62-08b0b806e241",
        "12345678-1234-1234-1234-123456789abc",
        db=mock_db,
    )

    assert revision == {"id": "full-revision-id"}
    repo.resolve_revision_id_prefix.assert_not_awaited()
    mock_db.execute.assert_awaited_once()
