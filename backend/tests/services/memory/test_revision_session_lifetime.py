"""History remains readable after a repository-owned session rolls back on exit."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session, make_transient_to_detached

from app.models.memory_unified import MemoryRevision
from app.services.memory._repo_revisions import RevisionRepository


@pytest.mark.asyncio
@pytest.mark.parametrize("single", [False, True])
async def test_revision_read_survives_owned_session_exit(single):
    row = MemoryRevision(id=uuid4(), memory_uuid=str(uuid4()), version=4,
                         content="Preserved evidence", scope="project", scope_id="neri")
    make_transient_to_detached(row)
    session = Session()
    session.add(row)

    class AsyncReadSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            session.rollback()
            session.close()

        async def execute(self, _statement):
            result = MagicMock()
            result.scalars.return_value.all.return_value = [row]
            result.scalar_one_or_none.return_value = row
            return result

        def expunge(self, obj):
            session.expunge(obj)

    with patch("app.services.memory._repo_revisions.async_session", return_value=AsyncReadSession()):
        repo = RevisionRepository()
        if single:
            result = await repo.get_revision(row.memory_uuid, str(row.id))
        else:
            result = (await repo.list_revisions(row.memory_uuid))[0]
    assert result is not None
    assert result.content == "Preserved evidence"
    assert result.scope_id == "neri"
