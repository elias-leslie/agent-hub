"""seed the local Qwen3-VL receipt/document model

Revision ID: c1d9e73a2b48
Revises: e6a2c40b91d5
Create Date: 2026-08-17 22:40:00.000000

``seed_model_catalog()`` never overwrites existing DB rows, so a new local model
has to arrive through a migration.

Why this model exists in the catalog at all: ``local/gemma4:12b-it-qat`` bills a
single 256-token image tile for a whole page, so a tall thermal receipt loses its
small print. Measured against a real Walmart receipt photo with known-good
extracted values, Gemma 4 mangled descriptions and barcodes, while
``qwen3-vl:8b-instruct`` returned 16/16 line items with exact subtotal, tax and
total in 12s (~4.1k image tokens — dynamic resolution).

The ``-instruct`` suffix is load bearing. The bare ``qwen3-vl:8b`` tag shares the
model digest of ``qwen3-vl:8b-thinking`` (ed12a4674d72); its reasoning cannot be
disabled through ``reasoning_effort``, ``think`` or ``chat_template_kwargs``, and
long extractions come back 200 OK with content="" after burning the whole token
budget on hidden reasoning.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d9e73a2b48"
down_revision: str | Sequence[str] | None = "e6a2c40b91d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MODEL_ID = "local/qwen3-vl:8b-instruct"


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            INSERT INTO models (
                id, alias, name, hint, provider,
                score_coding, score_reasoning, score_planning,
                score_tool_use, score_instruction, score_design,
                cost_input_per_m, cost_output_per_m,
                context_window, speed_tier, has_vision,
                supports_tool_execution, max_output_tokens,
                release_date, family, availability, is_active, source,
                created_at, updated_at
            ) VALUES (
                :id, 'local/qwen-vl', 'Qwen3-VL 8B Instruct (Local)',
                'Local receipt/document OCR', 'local',
                48, 60, 52, 56, 78, 50,
                0.00, 0.00,
                32768, 'fast', true,
                true, 16384,
                '2026-02-01', 'qwen',
                'requires_local_openai_endpoint; ~6.1gb_vram; use_instruct_not_bare_8b_tag',
                true, 'seed',
                now(), now()
            )
            ON CONFLICT (id) DO UPDATE SET
                is_active = true,
                has_vision = true,
                availability = EXCLUDED.availability,
                updated_at = now()
            """
        ),
        {"id": MODEL_ID},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("DELETE FROM models WHERE id = :id"), {"id": MODEL_ID})
