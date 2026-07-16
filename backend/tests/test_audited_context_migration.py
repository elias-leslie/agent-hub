"""Deterministic guards for the audited context data migration."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "7f4e2d1c9b8a_sync_audited_context_state.py"
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "audited_context_migration_7f4e2d1c9b8a",
        _MIGRATION_PATH,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class _RecordingConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> None:
        self.calls.append((str(statement), params))


def test_audited_context_snapshot_hash_and_transition_contract() -> None:
    migration = _load_migration_module()

    snapshot = migration._load_snapshot()

    assert snapshot["revision"] == migration.revision
    assert snapshot["persona_transition"]["agent_slug"] == "persona"
    assert snapshot["persona_transition"]["personality_prompt_slug"] == (
        "persona-personality-document"
    )
    assert snapshot["persona_transition"]["user_context_prompt_slug"] == (
        "persona-user-context"
    )
    assert snapshot["agent_system_prompt_mirror_sync"] == {
        "active_agents_only": False,
        "enabled_prompts_only": True,
        "priority": 0,
        "prompt_type": "agent_system",
        "role": "system",
    }
    assert snapshot["deactivate_agent_slugs"] == ["auditor"]


def test_persona_backfill_preserves_populated_row_authority() -> None:
    migration = _load_migration_module()
    connection = _RecordingConnection()
    transition = migration._load_snapshot()["persona_transition"]

    migration._migrate_legacy_persona_documents(connection, transition)

    assert len(connection.calls) == 2
    personality_sql, personality_params = connection.calls[0]
    user_context_sql, user_context_params = connection.calls[1]
    assert "COALESCE(BTRIM(persona_row.personality), '') = ''" in personality_sql
    assert "COALESCE(BTRIM(legacy_prompt.content), '') <> ''" in personality_sql
    assert personality_params == {
        "agent_slug": "persona",
        "prompt_slug": "persona-personality-document",
    }
    assert "COALESCE(BTRIM(persona_row.user_context), '') = ''" in user_context_sql
    assert "persona_row.user_profile IS NULL" in user_context_sql
    assert "persona_row.user_profile = '{}'::jsonb" in user_context_sql
    assert user_context_params == {
        "agent_slug": "persona",
        "prompt_slug": "persona-user-context",
    }


def test_upgrade_backfills_persona_before_disabling_legacy_prompts(monkeypatch: Any) -> None:
    migration = _load_migration_module()
    calls: list[str] = []
    snapshot = {
        "persona_transition": {},
        "prompts": [{"slug": "persona-personality-document"}],
        "remove_assignments": [],
        "ensure_assignments": [],
        "agent_system_prompt_mirror_sync": {},
        "agent_updates": [],
        "deactivate_agent_slugs": [],
        "delete_dangling_runtime_context_overrides": False,
    }
    monkeypatch.setattr(migration, "_load_snapshot", lambda: snapshot)
    monkeypatch.setattr(migration.op, "get_bind", lambda: object())
    monkeypatch.setattr(
        migration,
        "_migrate_legacy_persona_documents",
        lambda *_args: calls.append("persona_backfill"),
    )
    monkeypatch.setattr(
        migration,
        "_sync_prompt",
        lambda *_args: calls.append("prompt_sync"),
    )
    monkeypatch.setattr(
        migration,
        "_sync_canonical_agent_prompt_mirrors",
        lambda *_args: None,
    )
    monkeypatch.setattr(migration, "_replace_runtime_overrides", lambda *_args: None)

    migration.upgrade()

    assert calls == ["persona_backfill", "prompt_sync"]


def test_agent_prompt_mirror_sync_targets_every_canonical_assignment() -> None:
    migration = _load_migration_module()
    connection = _RecordingConnection()
    config = migration._load_snapshot()["agent_system_prompt_mirror_sync"]

    migration._sync_canonical_agent_prompt_mirrors(connection, config)

    assert len(connection.calls) == 1
    statement, params = connection.calls[0]
    assert "a.is_active" not in statement
    assert "p.enabled IS TRUE" in statement
    assert "p.prompt_type = :prompt_type" in statement
    assert "ap.role = :role" in statement
    assert "ap.priority = :priority" in statement
    assert "a.system_prompt IS DISTINCT FROM p.content" in statement
    assert params == {
        "priority": 0,
        "prompt_type": "agent_system",
        "role": "system",
    }


def test_legacy_agent_deactivation_is_a_forward_migration_not_seed_behavior() -> None:
    migration = _load_migration_module()
    connection = _RecordingConnection()

    migration._deactivate_legacy_agents(connection, ["auditor"])

    assert len(connection.calls) == 1
    statement, params = connection.calls[0]
    assert "SET is_active = false" in statement
    assert "WHERE slug = :slug AND is_active IS TRUE" in statement
    assert params == {"slug": "auditor"}
