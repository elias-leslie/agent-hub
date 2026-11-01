"""Restore endpoint: a newer unseen change is a 409 and the response names the new revision."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from app.api.memory_episodes_handlers import handle_restore_episode_revision
from app.api.memory_schemas import MemoryRestoreRequest
from app.services.memory._repo_revisions import RestoredMemory, RevisionConflictError

UUID = "12345678-0000-0000-0000-000000000000"


def _repo(**restore: object) -> SimpleNamespace:
    return SimpleNamespace(resolve_uuid_prefix=AsyncMock(return_value=UUID), restore_revision=AsyncMock(**restore))


async def test_restore_conflict_is_409() -> None:
    repo = _repo(side_effect=RevisionConflictError(UUID, expected=2, current=3))
    with patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=repo), \
            pytest.raises(HTTPException) as raised:
        await handle_restore_episode_revision(UUID, "abcd1234", MemoryRestoreRequest(expected_version=2))
    assert raised.value.status_code == 409
    assert repo.restore_revision.await_args.kwargs["expected_version"] == 2


async def test_restore_returns_the_new_revision_id() -> None:
    memory = SimpleNamespace(injection_tier="reference", version=4)
    repo = _repo(return_value=RestoredMemory(memory=memory, revision_id="rev-new", restored_from="rev-old"))
    with patch("app.api.memory_episodes_handlers.get_memory_repository", return_value=repo):
        response = await handle_restore_episode_revision(UUID, "rev-old", MemoryRestoreRequest())
    assert (response.version, response.revision_id, response.message) == (4, "rev-new", "Restored revision rev-old")
