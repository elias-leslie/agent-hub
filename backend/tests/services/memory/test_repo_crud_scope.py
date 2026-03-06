"""Tests for scope derivation in CrudRepository create path."""

from app.services.memory._repo_crud import _resolve_scope_from_group_id


class TestResolveScopeFromGroupId:
    """Ensure canonical scope/scope_id are derived from project group IDs."""

    def test_project_group_derives_project_scope(self) -> None:
        scope, scope_id = _resolve_scope_from_group_id(
            scope="global",
            scope_id=None,
            group_id="project-agent-hub",
        )
        assert scope == "project"
        assert scope_id == "agent-hub"

    def test_explicit_scope_is_preserved(self) -> None:
        scope, scope_id = _resolve_scope_from_group_id(
            scope="agent:persona",
            scope_id=None,
            group_id="project-agent-hub",
        )
        assert scope == "agent:persona"
        assert scope_id is None

    def test_non_project_group_remains_global(self) -> None:
        scope, scope_id = _resolve_scope_from_group_id(
            scope="global",
            scope_id=None,
            group_id="global",
        )
        assert scope == "global"
        assert scope_id is None

