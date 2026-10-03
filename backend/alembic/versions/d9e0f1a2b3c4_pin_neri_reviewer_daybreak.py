"""Pin the passive Neri reviewer to the owner-selected Daybreak route.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3

Only reviewer routing and its model identity sentence change. Reporter routing
and all evidence, target-access, and review requirements remain unchanged.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import text

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c8d9e0f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG = "neri-reviewer"
_PROMPT_SLUG = "neri-reviewer-system-prompt"
_PREVIOUS_MODEL = "codex/gpt-6.1-sol"
_MODEL = "codex/gpt-daybreak-blue-latest"
_PREVIOUS_IDENTITY = "record gpt-6.1-sol as the executing model."
_IDENTITY = "record gpt-daybreak-blue-latest as the executing model."
_PREVIOUS_DIGEST = "d9cd9f5689d28a91d73f2d9e62a50e3019476de1050331c9cdebc9a9a3a0e76e"
_DIGEST = "9b8fea5f5989cfd6f6b6549ea2fc8325cde446fcda8fe9879f74f5d00a54fa25"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _reviewer_prompt(current: str, *, reverse: bool = False) -> str:
    if _digest(current) not in (_PREVIOUS_DIGEST, _DIGEST):
        raise RuntimeError("Neri reviewer prompt has an unknown Daybreak-route revision")
    previous = current.replace(_IDENTITY, _PREVIOUS_IDENTITY)
    if _digest(previous) != _PREVIOUS_DIGEST or previous.count(_PREVIOUS_IDENTITY) != 1:
        raise RuntimeError("Neri reviewer model identity is inconsistent")
    return previous if reverse else previous.replace(_PREVIOUS_IDENTITY, _IDENTITY)


def _check_route(current: Mapping[str, Any]) -> None:
    actual = (
        current["primary_model_id"], current["thinking_level"],
        current["fallback_models"], current["escalation_model_id"], current["is_active"],
    )
    if actual not in (
        (_PREVIOUS_MODEL, "high", [], None, True),
        (_MODEL, "high", [], None, True),
    ):
        raise RuntimeError("Neri reviewer has an unknown Daybreak-route revision")


def _set_route(conn, *, reverse: bool = False) -> None:
    current = conn.execute(
        text(
            "SELECT primary_model_id, thinking_level, fallback_models, "
            "escalation_model_id, is_active, system_prompt "
            "FROM agents WHERE slug = :slug FOR UPDATE"
        ),
        {"slug": _SLUG},
    ).mappings().one_or_none()
    # The explicit agent seed owns reviewer creation. A schema-only install has
    # no reviewer to repin; an existing reviewer still requires every route and
    # canonical-prompt guard below.
    if current is None:
        return
    _check_route(current)
    prompt = _reviewer_prompt(current["system_prompt"], reverse=reverse)
    canonical = conn.execute(
        text("SELECT content FROM prompts WHERE slug = :slug FOR UPDATE"),
        {"slug": _PROMPT_SLUG},
    ).scalar_one()
    if canonical != current["system_prompt"]:
        raise RuntimeError("Neri reviewer canonical prompt and agent revision disagree")
    conn.execute(
        text(
            "UPDATE agents SET primary_model_id = :model, thinking_level = 'high', "
            "fallback_models = CAST('[]' AS JSON), escalation_model_id = NULL, "
            "system_prompt = :prompt, version = version + 1, updated_at = NOW() "
            "WHERE slug = :slug"
        ),
        {"slug": _SLUG, "model": _PREVIOUS_MODEL if reverse else _MODEL, "prompt": prompt},
    )
    conn.execute(
        text("UPDATE prompts SET content = :prompt, updated_at = NOW() WHERE slug = :slug"),
        {"slug": _PROMPT_SLUG, "prompt": prompt},
    )


def upgrade() -> None:
    _set_route(op.get_bind())


def downgrade() -> None:
    _set_route(op.get_bind(), reverse=True)
