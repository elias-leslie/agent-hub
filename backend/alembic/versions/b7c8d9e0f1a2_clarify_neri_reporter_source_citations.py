"""Clarify Neri reporter source-event citations.

Revision ID: b7c8d9e0f1a2
Revises: 9a6c8e1f4b20
"""

import hashlib
from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | Sequence[str] | None = "9a6c8e1f4b20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG = "neri-reporter"
_PROMPT_SLUG = "neri-reporter-system-prompt"
_PREVIOUS_SENTENCE = "Cite only exact supplied Neri evidence IDs."
_CITATION_SENTENCE = (
    "Cite only exact source_unit.events[].event_id values in every source_event_ids field. "
    "Neri owns report-level evidence record wiring; never place evidence_event_id in a "
    "source_event_ids field."
)
_PREVIOUS_DIGEST = "02402c560b4a049627af00cebbc15a53ce7dd43c13ba47527cb58da12ac8259d"
_DESIRED_DIGEST = "eda596549bee5bb54b3563a1fc87d1a840f586d774b5234af1bd17e99cb36283"


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _upgraded_prompt(current: str) -> str:
    current_digest = _digest(current)
    if current_digest == _DESIRED_DIGEST:
        return current
    if current_digest != _PREVIOUS_DIGEST or current.count(_PREVIOUS_SENTENCE) != 1:
        raise RuntimeError("Neri reporter prompt has an unknown pre-migration revision")
    desired = current.replace(_PREVIOUS_SENTENCE, _CITATION_SENTENCE)
    if _digest(desired) != _DESIRED_DIGEST:
        raise RuntimeError("Neri reporter citation prompt digest is inconsistent")
    return desired


def _downgraded_prompt(current: str) -> str:
    current_digest = _digest(current)
    if current_digest == _PREVIOUS_DIGEST:
        return current
    if current_digest != _DESIRED_DIGEST or current.count(_CITATION_SENTENCE) != 1:
        raise RuntimeError("Neri reporter prompt has an unknown post-migration revision")
    previous = current.replace(_CITATION_SENTENCE, _PREVIOUS_SENTENCE)
    if _digest(previous) != _PREVIOUS_DIGEST:
        raise RuntimeError("Neri reporter prior prompt digest is inconsistent")
    return previous


def _set_prompt(conn, prompt: str, *, version_delta: int) -> None:
    conn.execute(
        text(
            "UPDATE agents SET system_prompt = :prompt, "
            "version = GREATEST(1, version + :version_delta), updated_at = NOW() "
            "WHERE slug = :slug"
        ),
        {"slug": _SLUG, "prompt": prompt, "version_delta": version_delta},
    )
    conn.execute(
        text(
            "UPDATE prompts SET content = :prompt, updated_at = NOW() "
            "WHERE slug = :prompt_slug"
        ),
        {"prompt_slug": _PROMPT_SLUG, "prompt": prompt},
    )


def upgrade() -> None:
    conn = op.get_bind()
    current = conn.execute(
        text("SELECT system_prompt FROM agents WHERE slug = :slug FOR UPDATE"),
        {"slug": _SLUG},
    ).scalar_one()
    _set_prompt(conn, _upgraded_prompt(current), version_delta=1)


def downgrade() -> None:
    conn = op.get_bind()
    current = conn.execute(
        text("SELECT system_prompt FROM agents WHERE slug = :slug FOR UPDATE"),
        {"slug": _SLUG},
    ).scalar_one()
    _set_prompt(conn, _downgraded_prompt(current), version_delta=-1)
