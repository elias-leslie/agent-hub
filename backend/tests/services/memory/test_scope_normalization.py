"""Tests for legacy memory scope normalization."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.memory.scope_normalization import normalize_legacy_scope_rows


@pytest.mark.parametrize(
    ("scope", "scope_id", "group_id", "expected", "rules"),
    [
        ("project:neri", None, None, ("project", "neri", "project-neri"), ["legacy_prefixed_scope"]),
        ("project:neri", "kept", "project-kept", ("project", "kept", "project-kept"), ["legacy_prefixed_scope"]),
        ("global", None, "project-aico", ("project", "aico", "project-aico"), ["global_scope_project_group"]),
        ("project", "", "project-aico", ("project", "aico", "project-aico"), ["project_scope_missing_scope_id"]),
        ("global", None, None, ("global", None, None), []),
    ],
)
def test_normalized_scope_follows_the_legacy_rules_in_order(
    scope: str, scope_id: str | None, group_id: str | None, expected: tuple[str, str | None, str | None], rules: list[str]
) -> None:
    from app.services.memory.scope_normalization import _normalized_scope

    fields, applied = _normalized_scope(MagicMock(scope=scope, scope_id=scope_id, group_id=group_id))
    assert (fields["scope"], fields["scope_id"], fields["group_id"]) == expected
    assert applied == rules


@pytest.mark.asyncio
async def test_normalize_legacy_scope_rows_records_a_revision_per_changed_row() -> None:
    """Each normalized row gets a version bump and a revision; the rule counts are reported."""
    legacy = MagicMock(scope="project:neri", scope_id=None, group_id=None, version=1)
    mock_session = AsyncMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)
    mock_session.add = MagicMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(**{"scalars.return_value.all.return_value": [legacy]}))
    record = AsyncMock()

    with (
        patch("app.services.memory.scope_normalization.async_session", return_value=mock_session),
        patch("app.services.memory.scope_normalization.RevisionRepository.record_revision", record),
    ):
        result = await normalize_legacy_scope_rows()

    assert result == {"legacy_prefixed_scope": 1, "global_scope_project_group": 0, "project_scope_missing_scope_id": 0}
    assert (legacy.scope, legacy.scope_id, legacy.version) == ("project", "neri", 2)
    assert record.await_args is not None
    assert record.await_args.kwargs["action"] == "scope_normalize"
    mock_session.commit.assert_awaited_once()

