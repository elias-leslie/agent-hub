"""Routing, model catalog and prompt rows change at runtime, never in a new migration.

Agents, prompts and models are live DB state edited through the API/st (and exported
to the insert-only seed). Migrations after the cutoff may change schema only; a
data migration on those tables would overwrite runtime edits on the next deploy.
"""

from __future__ import annotations

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

# Every revision up to and including this one predates the rule and is grandfathered.
_CUTOFF = "c5e8a2d4f1b7"
_TABLES = r"(prompts|prompt_revisions|agents|agent_prompts|agent_versions|models|model_aliases|automation_definitions)"
_DML = re.compile(
    rf"(insert\s+into|update|delete\s+from)\s+\"?{_TABLES}\b"
    rf"|table\(\s*['\"]{_TABLES}['\"]"
    rf"|bulk_insert\(\s*{_TABLES}\b",
    re.IGNORECASE,
)


def test_new_migrations_do_not_write_routing_or_prompt_rows() -> None:
    backend = Path(__file__).resolve().parents[2]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    script = ScriptDirectory.from_config(config)
    offenders = [
        Path(revision.path).name
        for revision in script.iterate_revisions("heads", _CUTOFF)
        if revision.revision != _CUTOFF and _DML.search(Path(revision.path).read_text())
    ]
    assert offenders == [], (
        "Change agents, prompts, models and automation definitions through the API or st, "
        f"not a migration: {offenders}"
    )


def test_guard_recognizes_the_old_data_migration_shapes() -> None:
    assert _DML.search('conn.execute(sa.text("UPDATE agents SET primary_model_id = :m"))')
    assert _DML.search("DELETE FROM prompts WHERE slug = 'x'")
    assert _DML.search("prompts = sa.table('prompts', sa.column('slug'))")
    assert not _DML.search("INSERT INTO clients (id) VALUES (:id)")
    assert not _DML.search('op.add_column("agents", sa.Column("x", sa.Text()))')
