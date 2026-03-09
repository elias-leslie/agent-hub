"""Tests for memory CRUD detail normalization."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.memory.crud_operations import batch_get_episode_details, get_episode_details


@pytest.mark.asyncio
async def test_get_episode_details_normalizes_nullable_name() -> None:
    """Single-episode detail fetch should normalize legacy nullable fields."""
    now = datetime.now(UTC)
    mock_repo = AsyncMock()
    mock_repo.get_as_dict.return_value = {
        "uuid": "abc",
        "name": None,
        "content": "body",
        "source_description": None,
        "created_at": now,
    }

    with patch("app.services.memory.crud_operations.get_memory_repository", return_value=mock_repo):
        result = await get_episode_details("abc")

    assert result is not None
    assert result["name"] == ""
    assert result["source_description"] == ""


@pytest.mark.asyncio
async def test_batch_get_episode_details_normalizes_nullable_name() -> None:
    """Batch detail fetch should normalize legacy nullable fields consistently."""
    now = datetime.now(UTC)
    mock_repo = AsyncMock()
    mock_repo.batch_get.return_value = {
        "abc": {
            "uuid": "abc",
            "name": None,
            "content": "body",
            "source_description": None,
            "created_at": now,
        }
    }

    with patch("app.services.memory.crud_operations.get_memory_repository", return_value=mock_repo):
        result = await batch_get_episode_details(["abc"])

    assert result["abc"]["name"] == ""
    assert result["abc"]["source_description"] == ""
