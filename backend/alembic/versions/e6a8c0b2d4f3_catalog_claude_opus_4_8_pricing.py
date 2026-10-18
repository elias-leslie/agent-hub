"""keep Claude Opus 4.8 in the catalog (inactive) so its usage is priced

Revision ID: e6a8c0b2d4f3
Revises: d4f2a6c8e0b1
Create Date: 2026-10-18 15:45:00.000000

Coordinator sub-agents still run on claude-opus-4-8, which had no catalog row, so their calls
landed in the usage ledger without a list price (about 350 calls a day). Prices are from
platform.claude.com/docs/en/about-claude/pricing on 2026-10-18, per 1M tokens: $5 input,
$6.25 5-minute cache write, $0.50 cache hit, $25 output (1-hour writes are 2x input, which
the rates module derives). The row is inactive: it prices history, it is not offered for
routing. Other columns follow Opus 5.5; the ledger replay then prices the stored calls.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e6a8c0b2d4f3"
down_revision: str | Sequence[str] | None = "d4f2a6c8e0b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPIED = (
    "provider, score_coding, score_reasoning, score_planning, score_tool_use, score_instruction, score_design, "
    "pricing_unit, unit_price, service_tiers, context_window, speed_tier, can_generate_images, has_vision, "
    "can_edit_images, has_thinking, supports_pdf, supports_audio, supports_tool_execution, supports_verbosity, "
    "supports_xhigh, supports_session_cache, max_output_tokens, family, supports_chat, supports_typed_judgment, "
    "max_state_question_tokens, thinking_level_map, access_programs"
)


def upgrade() -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO models (id, alias, name, hint, cost_input_per_m, cost_output_per_m, cache_read_per_million,
                                cache_write_per_million, availability, is_active, sort_order, source, created_at,
                                updated_at, {_COPIED})
            SELECT 'claude-opus-4-8', NULL, 'Claude Opus 4.8', 'Retired; kept to price past usage', 5, 25, 0.5, 6.25,
                   'pricing_only; prices_platform.claude.com_2026-10-18', false, sort_order + 1, 'seed', now(), now(),
                   {_COPIED}
            FROM models WHERE id = 'claude-opus-5-5'
            ON CONFLICT (id) DO NOTHING
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM models WHERE id = 'claude-opus-4-8' AND source = 'seed' AND NOT is_active"))
