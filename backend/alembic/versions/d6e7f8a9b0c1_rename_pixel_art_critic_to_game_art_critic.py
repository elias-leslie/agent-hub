"""rename pixel art critic to game art critic

Revision ID: d6e7f8a9b0c1
Revises: c4a1b2d3e5f6
Create Date: 2026-06-21
"""

from collections.abc import Sequence

from sqlalchemy import text

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c4a1b2d3e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_SLUG = "pixel-art-critic"
NEW_SLUG = "game-art-critic"
OLD_PROMPT_SLUG = "pixel-art-critic-system-prompt"
NEW_PROMPT_SLUG = "game-art-critic-system-prompt"
NEW_NAME = "Game Art Critic"
NEW_DESCRIPTION = (
    "Game-ready visual critique specialist for 2D/3D game art, including pixel art, "
    "sprites, animations, tilesets, UI, environments, props, characters, textures, and "
    "model renders."
)
OLD_NAME = "Pixel Art Critic"
OLD_DESCRIPTION = (
    "Game-ready pixel-art image critique specialist for sprites, animations, tilesets, "
    "UI, and environments."
)
NEW_PROMPT = """You are Game Art Critic, an Agent Hub specialist for production game-art critique across 2D and 3D media.

Mission:
- Critique visual game assets so an agent can make concrete edits that improve production quality.
- Cover 2D sprites, pixel art, sprite sheets, tilesets, UI/icons, VFX, environments, portraits, concept art, 3D model renders, materials/textures, props, characters, and animation proofs.
- Optimize for the project lead's stated taste when supplied: no generic placeholder/slop, strong silhouette, coherent game identity, disciplined medium-specific technique, animation/readability readiness, and engine-ready constraints.

Rules:
- First verify vision: name 3-5 concrete observed elements actually visible in the image. If you cannot see the image, say so and stop; do not hallucinate.
- Do not invent weapons, gear, anatomy, materials, topology, or background elements that are not visible.
- Do not copy protected reference art. References are quality bars and technique examples only.
- Prioritize comments that can become local edit instructions: exact region, exact visual problem, exact change.
- Separate blocking production issues from optional polish.
- Apply medium-specific checks:
  - Pixel art: hard clusters, no blurry pseudo-pixel art, binary alpha, palette discipline, silhouette at native scale.
  - 2D painted/vector/UI: readable shape language, value grouping, scale, icon semantics, material separation, export-safe edges.
  - Tiles/environments: seams, repetition, material read, collision/navigation/occlusion affordances, scale consistency.
  - 3D/model renders: silhouette, proportions, material/texture read, UV/normal/lighting artifacts when visible, rig/animation readiness, LOD/readability.
  - Animation: pivot/anchor, silhouette drift, contact/weight, limb separation, frame-to-frame identity, timing/readability risks.

Default output:
1. Vision sanity: concrete observed elements.
2. Verdict: approve / approve-with-revisions / reject.
3. Blocking issues: exact region + why it hurts quality.
4. Concrete edit instructions: actionable local changes.
5. Animation/engine-readiness risks.
6. What not to change.
7. Usefulness score 1-10."""
OLD_PROMPT = """You are Pixel Art Critic, an Agent Hub specialist for game-ready pixel-art asset critique.

Mission:
- Critique visual game assets so an agent can make concrete edits that improve production quality.
- Be especially strict for pixel-art sprites, animation frames, tilesets, icons, environments, and UI assets.
- Optimize for the project lead's stated taste when supplied: no generic placeholder/slop, strong silhouette, disciplined hard pixel clusters, no blurry pseudo-pixel art, coherent game identity, animation readiness, and engine-ready constraints.

Rules:
- First verify vision: name 3-5 concrete observed elements actually visible in the image. If you cannot see the image, say so and stop; do not hallucinate.
- Do not invent weapons, gear, anatomy, or background elements that are not visible.
- Do not copy protected reference art. References are only quality bars and technique examples.
- Prioritize comments that can become local edit instructions: exact region, exact visual problem, exact change.
- Separate blocking production issues from optional polish.
- For animations, call out pivot/anchor, silhouette drift, foot contact, limb separation, frame-to-frame identity, and readability risks.
- For tiles/environments, call out seams, value grouping, material read, tiling artifacts, scale, and engine export risks.

Default output:
1. Vision sanity: concrete observed elements.
2. Verdict: approve / approve-with-revisions / reject.
3. Blocking issues: exact region + why it hurts quality.
4. Concrete edit instructions: actionable local changes.
5. Animation/engine-readiness risks.
6. What not to change.
7. Usefulness score 1-10."""


def _scalar(sql: str, **params: object) -> object | None:
    return op.get_bind().execute(text(sql), params).scalar_one_or_none()


def _upsert_system_prompt(agent_slug: str, prompt_slug: str, name: str, content: str) -> None:
    conn = op.get_bind()
    conn.execute(
        text(
            """
            INSERT INTO prompts (
                slug, name, content, description, is_global, enabled, exclude_agents,
                owner_agent_id, prompt_type, deletion_locked
            )
            SELECT
                :prompt_slug,
                :name,
                :content,
                'Primary system prompt for ' || a.name || '.',
                false,
                true,
                '[]'::json,
                a.id,
                'agent_system',
                true
            FROM agents a
            WHERE a.slug = :agent_slug
            ON CONFLICT (slug) DO UPDATE SET
                name = EXCLUDED.name,
                content = EXCLUDED.content,
                description = EXCLUDED.description,
                owner_agent_id = EXCLUDED.owner_agent_id,
                prompt_type = EXCLUDED.prompt_type,
                deletion_locked = EXCLUDED.deletion_locked,
                enabled = EXCLUDED.enabled,
                updated_at = NOW()
            """
        ),
        {
            "agent_slug": agent_slug,
            "prompt_slug": prompt_slug,
            "name": name,
            "content": content,
        },
    )
    conn.execute(
        text(
            """
            INSERT INTO agent_prompts (agent_id, prompt_id, role, priority)
            SELECT a.id, p.id, 'system', 0
            FROM agents a
            JOIN prompts p ON p.slug = :prompt_slug
            WHERE a.slug = :agent_slug
            ON CONFLICT (agent_id, prompt_id) DO UPDATE SET
                role = EXCLUDED.role,
                priority = EXCLUDED.priority
            """
        ),
        {"agent_slug": agent_slug, "prompt_slug": prompt_slug},
    )


def upgrade() -> None:
    conn = op.get_bind()
    old_id = _scalar("SELECT id FROM agents WHERE slug = :slug", slug=OLD_SLUG)
    new_id = _scalar("SELECT id FROM agents WHERE slug = :slug", slug=NEW_SLUG)

    if old_id is not None and new_id is None:
        conn.execute(
            text(
                """
                UPDATE agents
                SET slug = :new_slug,
                    name = :name,
                    description = :description,
                    system_prompt = :prompt,
                    is_active = true,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = :old_id
                """
            ),
            {
                "new_slug": NEW_SLUG,
                "name": NEW_NAME,
                "description": NEW_DESCRIPTION,
                "prompt": NEW_PROMPT,
                "old_id": old_id,
            },
        )
        conn.execute(
            text(
                """
                UPDATE prompts
                SET slug = :new_prompt_slug,
                    name = :name,
                    content = :prompt,
                    description = :description,
                    updated_at = NOW()
                WHERE slug = :old_prompt_slug
                """
            ),
            {
                "new_prompt_slug": NEW_PROMPT_SLUG,
                "old_prompt_slug": OLD_PROMPT_SLUG,
                "name": f"{NEW_NAME} System Prompt",
                "description": f"Primary system prompt for {NEW_NAME}.",
                "prompt": NEW_PROMPT,
            },
        )
    elif new_id is not None:
        conn.execute(
            text(
                """
                UPDATE agents
                SET name = :name,
                    description = :description,
                    system_prompt = :prompt,
                    is_active = true,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = :new_id
                """
            ),
            {
                "name": NEW_NAME,
                "description": NEW_DESCRIPTION,
                "prompt": NEW_PROMPT,
                "new_id": new_id,
            },
        )
        if old_id is not None:
            conn.execute(
                text("UPDATE agents SET is_active = false, updated_at = NOW() WHERE id = :old_id"),
                {"old_id": old_id},
            )

    _upsert_system_prompt(
        NEW_SLUG,
        NEW_PROMPT_SLUG,
        f"{NEW_NAME} System Prompt",
        NEW_PROMPT,
    )


def downgrade() -> None:
    conn = op.get_bind()
    old_id = _scalar("SELECT id FROM agents WHERE slug = :slug", slug=OLD_SLUG)
    new_id = _scalar("SELECT id FROM agents WHERE slug = :slug", slug=NEW_SLUG)

    if new_id is not None and old_id is None:
        conn.execute(
            text(
                """
                UPDATE agents
                SET slug = :old_slug,
                    name = :name,
                    description = :description,
                    system_prompt = :prompt,
                    is_active = true,
                    version = version + 1,
                    updated_at = NOW()
                WHERE id = :new_id
                """
            ),
            {
                "old_slug": OLD_SLUG,
                "name": OLD_NAME,
                "description": OLD_DESCRIPTION,
                "prompt": OLD_PROMPT,
                "new_id": new_id,
            },
        )
        conn.execute(
            text(
                """
                UPDATE prompts
                SET slug = :old_prompt_slug,
                    name = :name,
                    content = :prompt,
                    description = :description,
                    updated_at = NOW()
                WHERE slug = :new_prompt_slug
                """
            ),
            {
                "old_prompt_slug": OLD_PROMPT_SLUG,
                "new_prompt_slug": NEW_PROMPT_SLUG,
                "name": f"{OLD_NAME} System Prompt",
                "description": f"Primary system prompt for {OLD_NAME}.",
                "prompt": OLD_PROMPT,
            },
        )
    elif old_id is not None:
        conn.execute(
            text("UPDATE agents SET is_active = true, updated_at = NOW() WHERE id = :old_id"),
            {"old_id": old_id},
        )
