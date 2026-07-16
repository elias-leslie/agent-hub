"""Sync the approved Agent Hub context and persona-authority transition.

Revision ID: 7f4e2d1c9b8a
Revises: 6e3c4c3cffac
Create Date: 2026-07-16

Prompt bodies live in an immutable revision-specific JSON snapshot rather than
Python.  This migration is targeted to the audited rows; it does not turn the
insert-only seed path into an updater or overwrite unrelated prompt state.

Persona identity and user state stay on existing ``persona`` rows.  The
migration preserves those user-owned values while disabling and unassigning
the two legacy prompt-backed document rows.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import sqlalchemy as sa

from alembic import op

revision: str = "7f4e2d1c9b8a"
down_revision: str | Sequence[str] | None = "6e3c4c3cffac"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "7f4e2d1c9b8a_audited_context.json"
)
_PROMPT_FIELD_SQL = {
    "name": "name = :name",
    "description": "description = :description",
    "content": "content = :content",
    "is_global": "is_global = :is_global",
    "enabled": "enabled = :enabled",
    "boot_eligible": "boot_eligible = :boot_eligible",
    "exclude_agents": "exclude_agents = CAST(:exclude_agents AS JSON)",
}
_AGENT_FIELD_SQL = {
    "primary_model_id": "primary_model_id = :primary_model_id",
    "fallback_models": "fallback_models = CAST(:fallback_models AS JSON)",
    "thinking_level": "thinking_level = :thinking_level",
    "temperature": "temperature = :temperature",
}


def _canonical_payload(snapshot: Mapping[str, Any]) -> bytes:
    payload = {key: value for key, value in snapshot.items() if key != "_metadata"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _load_snapshot() -> dict[str, Any]:
    snapshot = json.loads(_SNAPSHOT_PATH.read_text())
    if snapshot.get("revision") != revision:
        raise RuntimeError("Audited context snapshot revision mismatch")
    expected_hash = snapshot.get("_metadata", {}).get("payload_sha256")
    actual_hash = hashlib.sha256(_canonical_payload(snapshot)).hexdigest()
    if not expected_hash or actual_hash != expected_hash:
        raise RuntimeError("Audited context snapshot hash mismatch")
    return snapshot


def _normalize_value(key: str, value: Any) -> Any:
    if key in {"exclude_agents", "fallback_models"}:
        return list(value or [])
    return value


def _prompt_row(conn: Any, slug: str) -> Mapping[str, Any] | None:
    return conn.execute(
        sa.text(
            """
            SELECT id, slug, name, content, description, is_global, enabled,
                   boot_eligible, exclude_agents, owner_agent_id, prompt_type,
                   deletion_locked
            FROM prompts
            WHERE slug = :slug
            """
        ),
        {"slug": slug},
    ).mappings().one_or_none()


def _insert_prompt_if_missing(
    conn: Any,
    *,
    slug: str,
    fields: Mapping[str, Any],
    create: Mapping[str, Any] | None,
) -> bool:
    if _prompt_row(conn, slug) is not None or create is None:
        return False
    owner_slug = create.get("owner_agent_slug")
    conn.execute(
        sa.text(
            """
            INSERT INTO prompts (
                slug, name, content, description, is_global, enabled,
                boot_eligible, exclude_agents, owner_agent_id, prompt_type,
                deletion_locked
            )
            VALUES (
                :slug, :name, :content, :description, :is_global, :enabled,
                :boot_eligible, CAST(:exclude_agents AS JSON),
                (SELECT id FROM agents WHERE slug = :owner_slug),
                :prompt_type, :deletion_locked
            )
            """
        ),
        {
            "slug": slug,
            "name": fields["name"],
            "content": fields["content"],
            "description": fields.get("description"),
            "is_global": fields["is_global"],
            "enabled": fields["enabled"],
            "boot_eligible": fields["boot_eligible"],
            "exclude_agents": json.dumps(fields.get("exclude_agents") or []),
            "owner_slug": owner_slug,
            "prompt_type": create["prompt_type"],
            "deletion_locked": create["deletion_locked"],
        },
    )
    return True


def _record_prompt_revision(conn: Any, row: Mapping[str, Any], *, action: str) -> None:
    conn.execute(
        sa.text(
            """
            INSERT INTO prompt_revisions (
                prompt_id, prompt_slug, prompt_name, action, content,
                description, is_global, enabled, exclude_agents,
                owner_agent_id, prompt_type, deletion_locked, boot_eligible,
                content_hash, changed_by, change_reason
            )
            VALUES (
                :prompt_id, :prompt_slug, :prompt_name, :action, :content,
                :description, :is_global, :enabled, CAST(:exclude_agents AS JSON),
                :owner_agent_id, :prompt_type, :deletion_locked, :boot_eligible,
                :content_hash, :changed_by, :change_reason
            )
            """
        ),
        {
            "prompt_id": row["id"],
            "prompt_slug": row["slug"],
            "prompt_name": row["name"],
            "action": action,
            "content": row["content"],
            "description": row["description"],
            "is_global": row["is_global"],
            "enabled": row["enabled"],
            "exclude_agents": json.dumps(row["exclude_agents"] or []),
            "owner_agent_id": row["owner_agent_id"],
            "prompt_type": row["prompt_type"],
            "deletion_locked": row["deletion_locked"],
            "boot_eligible": row["boot_eligible"],
            "content_hash": hashlib.sha256(row["content"].encode()).hexdigest(),
            "changed_by": "migration:7f4e2d1c9b8a",
            "change_reason": "Apply approved full context and memory audit remediation",
        },
    )


def _sync_prompt(conn: Any, item: Mapping[str, Any]) -> None:
    slug = item["slug"]
    fields = dict(item["fields"])
    content = fields.get("content")
    if content is not None:
        actual_hash = hashlib.sha256(content.encode()).hexdigest()
        if actual_hash != item.get("content_sha256"):
            raise RuntimeError(f"Prompt snapshot content hash mismatch: {slug}")

    inserted = _insert_prompt_if_missing(
        conn,
        slug=slug,
        fields=fields,
        create=item.get("create"),
    )
    row = _prompt_row(conn, slug)
    if row is None:
        return

    changed = inserted or any(
        _normalize_value(key, row[key]) != _normalize_value(key, value)
        for key, value in fields.items()
    )
    if not inserted and changed:
        assignments = [_PROMPT_FIELD_SQL[key] for key in fields]
        params = {"slug": slug}
        for key, value in fields.items():
            params[key] = (
                json.dumps(value or [])
                if key == "exclude_agents"
                else value
            )
        conn.execute(
            sa.text(
                f"UPDATE prompts SET {', '.join(assignments)}, updated_at = NOW() "
                "WHERE slug = :slug"
            ),
            params,
        )

    if changed:
        updated = _prompt_row(conn, slug)
        if updated is None:
            raise RuntimeError(f"Prompt disappeared during migration: {slug}")
        _record_prompt_revision(conn, updated, action="create" if inserted else "update")


def _remove_assignment(conn: Any, item: Mapping[str, Any]) -> None:
    conn.execute(
        sa.text(
            """
            DELETE FROM agent_prompts ap
            USING agents a, prompts p
            WHERE ap.agent_id = a.id
              AND ap.prompt_id = p.id
              AND a.slug = :agent_slug
              AND p.slug = :prompt_slug
            """
        ),
        dict(item),
    )


def _ensure_assignment(conn: Any, item: Mapping[str, Any]) -> None:
    ids = conn.execute(
        sa.text(
            """
            SELECT a.id AS agent_id, p.id AS prompt_id
            FROM agents a
            CROSS JOIN prompts p
            WHERE a.slug = :agent_slug AND p.slug = :prompt_slug
            """
        ),
        dict(item),
    ).mappings().one_or_none()
    if ids is None:
        return
    existing = conn.execute(
        sa.text(
            """
            SELECT id FROM agent_prompts
            WHERE agent_id = :agent_id AND prompt_id = :prompt_id
            """
        ),
        dict(ids),
    ).scalar_one_or_none()
    params = {
        **dict(ids),
        "role": item["role"],
        "priority": item["priority"],
    }
    if existing is None:
        conn.execute(
            sa.text(
                """
                INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
                VALUES (:agent_id, :prompt_id, :role, :priority)
                """
            ),
            params,
        )
        return
    conn.execute(
        sa.text(
            """
            UPDATE agent_prompts
            SET role = :role, priority = :priority
            WHERE agent_id = :agent_id AND prompt_id = :prompt_id
            """
        ),
        params,
    )


def _migrate_legacy_persona_documents(
    conn: Any,
    transition: Mapping[str, Any],
) -> None:
    """Backfill prompt-backed persona text only when row authority is empty."""
    shared_params = {"agent_slug": transition["agent_slug"]}
    conn.execute(
        sa.text(
            """
            UPDATE persona persona_row
            SET personality = legacy_prompt.content,
                updated_at = NOW()
            FROM agents persona_agent, prompts legacy_prompt
            WHERE persona_row.agent_id = persona_agent.id
              AND persona_agent.slug = :agent_slug
              AND legacy_prompt.slug = :prompt_slug
              AND COALESCE(BTRIM(persona_row.personality), '') = ''
              AND COALESCE(BTRIM(legacy_prompt.content), '') <> ''
            """
        ),
        {
            **shared_params,
            "prompt_slug": transition["personality_prompt_slug"],
        },
    )
    conn.execute(
        sa.text(
            """
            UPDATE persona persona_row
            SET user_context = legacy_prompt.content,
                updated_at = NOW()
            FROM agents persona_agent, prompts legacy_prompt
            WHERE persona_row.agent_id = persona_agent.id
              AND persona_agent.slug = :agent_slug
              AND legacy_prompt.slug = :prompt_slug
              AND COALESCE(BTRIM(persona_row.user_context), '') = ''
              AND (
                  persona_row.user_profile IS NULL
                  OR persona_row.user_profile = '{}'::jsonb
              )
              AND COALESCE(BTRIM(legacy_prompt.content), '') <> ''
            """
        ),
        {
            **shared_params,
            "prompt_slug": transition["user_context_prompt_slug"],
        },
    )


def _sync_canonical_agent_prompt_mirrors(
    conn: Any,
    config: Mapping[str, Any],
) -> None:
    """Align every legacy agent mirror with its enabled canonical prompt."""
    conn.execute(
        sa.text(
            """
            UPDATE agents a
            SET system_prompt = p.content,
                version = a.version + 1,
                updated_at = NOW()
            FROM agent_prompts ap, prompts p
            WHERE ap.agent_id = a.id
              AND p.id = ap.prompt_id
              AND p.enabled IS TRUE
              AND p.prompt_type = :prompt_type
              AND ap.role = :role
              AND ap.priority = :priority
              AND a.system_prompt IS DISTINCT FROM p.content
            """
        ),
        {
            "prompt_type": config["prompt_type"],
            "role": config["role"],
            "priority": config["priority"],
        },
    )


def _sync_agent_fields(conn: Any, item: Mapping[str, Any]) -> None:
    slug = item["slug"]
    fields = dict(item["fields"])
    row = conn.execute(
        sa.text(
            """
            SELECT primary_model_id, fallback_models, thinking_level, temperature
            FROM agents WHERE slug = :slug
            """
        ),
        {"slug": slug},
    ).mappings().one_or_none()
    if row is None:
        return
    changed = any(
        _normalize_value(key, row[key]) != _normalize_value(key, value)
        for key, value in fields.items()
    )
    if not changed:
        return
    assignments = [_AGENT_FIELD_SQL[key] for key in fields]
    params = {"slug": slug}
    for key, value in fields.items():
        params[key] = json.dumps(value or []) if key == "fallback_models" else value
    conn.execute(
        sa.text(
            f"UPDATE agents SET {', '.join(assignments)}, "
            "version = version + 1, updated_at = NOW() WHERE slug = :slug"
        ),
        params,
    )


def _deactivate_legacy_agents(conn: Any, slugs: Sequence[str]) -> None:
    """Apply one-time lifecycle transitions that do not belong in seeds."""
    for slug in slugs:
        conn.execute(
            sa.text(
                """
                UPDATE agents
                SET is_active = false,
                    version = version + 1,
                    updated_at = NOW()
                WHERE slug = :slug AND is_active IS TRUE
                """
            ),
            {"slug": slug},
        )


def _delete_dangling_overrides(conn: Any) -> None:
    conn.execute(
        sa.text(
            """
            DELETE FROM runtime_context_overrides r
            WHERE (
                r.source_type = 'prompt'
                AND NOT EXISTS (
                    SELECT 1 FROM prompts p
                    WHERE p.slug = r.source_id AND p.enabled IS TRUE
                )
            ) OR (
                r.source_type = 'memory'
                AND NOT EXISTS (
                    SELECT 1 FROM memories m
                    WHERE CAST(m.id AS TEXT) = r.source_id
                      AND m.status = 'active'
                )
            )
            """
        )
    )


def _replace_runtime_overrides(conn: Any, snapshot: Mapping[str, Any]) -> None:
    for source_id in snapshot["replace_runtime_override_source_ids"]:
        conn.execute(
            sa.text(
                """
                DELETE FROM runtime_context_overrides
                WHERE source_type = 'prompt' AND source_id = :source_id
                """
            ),
            {"source_id": source_id},
        )
    for item in snapshot["runtime_context_overrides"]:
        conn.execute(
            sa.text(
                """
                INSERT INTO runtime_context_overrides (
                    consumer_profile, project_id, source_type, source_id,
                    mode, position, enabled, note, tier_override
                )
                VALUES (
                    :consumer_profile, :project_id, :source_type, :source_id,
                    :mode, :position, :enabled, :note, :tier_override
                )
                """
            ),
            dict(item),
        )


def upgrade() -> None:
    snapshot = _load_snapshot()
    conn = op.get_bind()

    _migrate_legacy_persona_documents(conn, snapshot["persona_transition"])
    for item in snapshot["prompts"]:
        _sync_prompt(conn, item)
    for item in snapshot["remove_assignments"]:
        _remove_assignment(conn, item)
    for item in snapshot["ensure_assignments"]:
        _ensure_assignment(conn, item)
    _sync_canonical_agent_prompt_mirrors(
        conn,
        snapshot["agent_system_prompt_mirror_sync"],
    )
    for item in snapshot["agent_updates"]:
        _sync_agent_fields(conn, item)
    _deactivate_legacy_agents(conn, snapshot["deactivate_agent_slugs"])

    if snapshot["delete_dangling_runtime_context_overrides"]:
        _delete_dangling_overrides(conn)
    _replace_runtime_overrides(conn, snapshot)


def downgrade() -> None:
    """Irreversible audited data reconciliation; prompt revisions preserve rollback data."""
