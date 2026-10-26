"""Export current DB agents and prompts to seed_data.json, and the model catalog to model_catalog.json.

One-way sync: DB (source of truth) → seed file (for new installs).
Run with: python -m scripts.export_seeds

This is the ONLY way seed_data.json should be updated. Never edit it by hand.

The seed file is published with the repository, so the export is limited to the
general-purpose agents and prompts in PUBLIC_AGENT_SLUGS and PUBLIC_PROMPT_SLUGS.
Deployment-specific agents and prompts stay in the database (and its backups);
add a slug here only when its exported content is fit to publish.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models import Agent
from app.models.model_catalog import ModelAlias, ModelCatalogEntry
from app.models.prompt import AgentPrompt, Prompt
from app.services.prompt_catalog import build_agent_system_prompt_slug

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

SEED_FILE = Path(__file__).parent / "seed_agents_data" / "seed_data.json"
MODEL_CATALOG_FILE = Path(__file__).parent / "seed_agents_data" / "model_catalog.json"
_MODEL_TIMESTAMPS = {"created_at", "updated_at"}

# Fields to export for each agent (matches seed_agents.py import fields)
AGENT_EXPORT_FIELDS = [
    "slug", "name", "description", "system_prompt",
    "primary_model_id", "fallback_models", "escalation_model_id",
    "strategies", "temperature", "thinking_level",
    "is_coding_agent", "memory_config", "max_concurrency",
]

DEACTIVATE_SLUGS = ["auditor", "memory-curator"]

PUBLIC_AGENT_SLUGS = frozenset({
    "analyst", "chat", "coder", "committee-router-v1", "committee-synthesizer-v1",
    "complexity-assessor", "context-compactor", "critic", "debugger", "designer",
    "equity-analyst", "explorer", "git-agent", "image-gen", "investment-committee",
    "learning-extractor", "market-pulse-scout", "memory-rater", "note-formatter",
    "note-titler", "optimizer", "planner", "prompt-builder",
    "provider-liveness-probe", "reasoner", "refactor", "researcher", "reviewer",
    "risk-manager", "specifier", "summarizer", "supervisor", "test-writer", "tester",
    "triager", "ui-mockup-designer", "ux-polisher", "validator", "verifier",
    "voice-responder", "worker",
})
PUBLIC_PROMPT_SLUGS = frozenset({
    "coding-golden-rule", "graphify-workspace-map", "narration-tags",
    "workspace-search-discipline",
})
AGENT_SYSTEM_PROMPT_TYPE = "agent_system"

PROMPT_EXPORT_FIELDS = [
    "slug", "name", "content", "description",
    "is_global", "enabled", "context_policy", "boot_eligible", "exclude_agents", "prompt_type", "deletion_locked",
]


def _serialize_agent(agent: Agent, system_prompt_override: str | None) -> dict:
    """Serialize an agent to a seed-compatible dictionary."""
    data: dict = {}
    for field in AGENT_EXPORT_FIELDS:
        value = getattr(agent, field, None)
        if field == "system_prompt" and system_prompt_override is not None:
            value = system_prompt_override
        if value is not None:
            data[field] = value
    return data


def _serialize_prompt(prompt: Prompt, owner_agent_slug: str | None) -> dict:
    """Serialize a reusable prompt to a seed-compatible dictionary."""
    data: dict = {}
    for field in PROMPT_EXPORT_FIELDS:
        value = getattr(prompt, field, None)
        if value is not None:
            data[field] = value
    if owner_agent_slug:
        data["owner_agent_slug"] = owner_agent_slug
    return data


def _normalized_seed_payload(seed_data: dict) -> dict:
    """Return a comparable seed payload without timestamp churn."""
    metadata = seed_data.get("_metadata", {})
    normalized_metadata = {k: v for k, v in metadata.items() if k != "generated_at"}
    normalized = dict(seed_data)
    normalized["_metadata"] = normalized_metadata
    return normalized


async def export_seeds(db: AsyncSession) -> dict:
    """Export the public active agents and their prompts to a seed-compatible structure."""
    # Fetch all active agents
    result = await db.execute(
        select(Agent)
        .where(Agent.is_active.is_(True), Agent.slug.in_(PUBLIC_AGENT_SLUGS))
        .order_by(Agent.slug)
    )
    agents = list(result.scalars().all())

    # For each agent, check if there's a DB-stored system prompt override
    agent_dicts = []
    for agent in agents:
        prompt_slug = build_agent_system_prompt_slug(agent.slug)
        prompt_result = await db.execute(
            select(Prompt).where(Prompt.slug == prompt_slug, Prompt.enabled.is_(True))
        )
        prompt = prompt_result.scalar_one_or_none()
        override = prompt.content if prompt else None

        agent_dicts.append(_serialize_agent(agent, override))

    active_agent_ids = [agent.id for agent in agents]
    active_agent_slugs = {agent.id: agent.slug for agent in agents}

    assigned_prompt_result = await db.execute(
        select(Prompt.slug)
        .join(AgentPrompt, AgentPrompt.prompt_id == Prompt.id)
        .where(
            AgentPrompt.agent_id.in_(active_agent_ids),
            Prompt.enabled.is_(True),
            Prompt.prompt_type != AGENT_SYSTEM_PROMPT_TYPE,
        )
    )
    prompt_slugs = set(assigned_prompt_result.scalars().all())

    global_prompt_result = await db.execute(
        select(Prompt.slug).where(
            or_(
                Prompt.is_global.is_(True),
                Prompt.context_policy["scope"].as_string().in_(["project", "agent"]),
                func.json_array_length(Prompt.context_policy["workflows"]) > 0,
            ),
            Prompt.enabled.is_(True),
            Prompt.prompt_type != AGENT_SYSTEM_PROMPT_TYPE,
        )
    )
    prompt_slugs.update(global_prompt_result.scalars().all())
    prompt_slugs &= PUBLIC_PROMPT_SLUGS

    prompt_dicts = []
    if prompt_slugs:
        prompt_result = await db.execute(
            select(Prompt).where(Prompt.slug.in_(prompt_slugs)).order_by(Prompt.slug)
        )
        for prompt in prompt_result.scalars().all():
            prompt_dicts.append(
                _serialize_prompt(prompt, active_agent_slugs.get(prompt.owner_agent_id))
            )

    assignment_dicts = []
    if prompt_slugs:
        assignment_result = await db.execute(
            select(Agent.slug, Prompt.slug, AgentPrompt.role, AgentPrompt.priority)
            .join(AgentPrompt, AgentPrompt.agent_id == Agent.id)
            .join(Prompt, Prompt.id == AgentPrompt.prompt_id)
            .where(
                Agent.id.in_(active_agent_ids),
                Prompt.slug.in_(prompt_slugs),
                Prompt.enabled.is_(True),
            )
            .order_by(Agent.slug, AgentPrompt.priority, Prompt.slug)
        )
        assignment_dicts = [
            {
                "agent_slug": agent_slug,
                "prompt_slug": prompt_slug,
                "role": role,
                "priority": priority,
            }
            for agent_slug, prompt_slug, role, priority in assignment_result.all()
        ]

    return {
        "_metadata": {
            "generated_at": datetime.now(UTC).isoformat(),
            "generator": "scripts/export_seeds.py",
            "warning": "AUTO-GENERATED from database. Do NOT edit this file.",
            "source_of_truth": "Database prompt store. Use 'st prompt update' and agent API for changes.",
            "agent_count": len(agent_dicts),
            "prompt_count": len(prompt_dicts),
            "agent_prompt_assignment_count": len(assignment_dicts),
        },
        "agents": agent_dicts,
        "prompts": prompt_dicts,
        "agent_prompt_assignments": assignment_dicts,
        "deactivate_slugs": DEACTIVATE_SLUGS,
    }


async def export_model_catalog(db: AsyncSession) -> dict:
    """Export every models and model_aliases row (the catalog a fresh install starts from)."""
    model_columns = [c.name for c in ModelCatalogEntry.__table__.columns if c.name not in _MODEL_TIMESTAMPS]
    rows = (await db.execute(
        select(ModelCatalogEntry).order_by(ModelCatalogEntry.sort_order, ModelCatalogEntry.id)
    )).scalars().all()
    aliases = (await db.execute(select(ModelAlias).order_by(ModelAlias.alias))).scalars().all()
    return {
        "_metadata": {
            "generator": "scripts/export_seeds.py",
            "warning": "AUTO-GENERATED from database. Do NOT edit this file.",
            "source_of_truth": "Database models/model_aliases tables. Change models through the models API.",
        },
        "models": [{name: getattr(row, name) for name in model_columns} for row in rows],
        "aliases": [
            {"alias": row.alias, "model_id": row.model_id, "alias_type": row.alias_type, "source": row.source}
            for row in aliases
        ],
    }


def _write_if_changed(path: Path, payload: dict) -> None:
    rendered = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    if not path.exists() or path.read_text() != rendered:
        path.write_text(rendered)


async def main() -> None:
    """Export seeds from database to JSON file."""
    db_url = settings.agent_hub_db_url.replace("postgresql://", "postgresql+asyncpg://")
    engine = create_async_engine(db_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    async with session_factory() as db:
        seed_data = await export_seeds(db)
        _write_if_changed(MODEL_CATALOG_FILE, await export_model_catalog(db))

    if SEED_FILE.exists():
        try:
            existing_data = json.loads(SEED_FILE.read_text())
        except json.JSONDecodeError:
            existing_data = None
        else:
            if _normalized_seed_payload(existing_data) == _normalized_seed_payload(seed_data):
                existing_generated_at = existing_data.get("_metadata", {}).get("generated_at")
                if existing_generated_at:
                    seed_data["_metadata"]["generated_at"] = existing_generated_at

    rendered = json.dumps(seed_data, indent=2, ensure_ascii=False) + "\n"
    if not SEED_FILE.exists() or SEED_FILE.read_text() != rendered:
        SEED_FILE.write_text(rendered)
    logger.info(
        "Exported %d agents to %s",
        seed_data["_metadata"]["agent_count"],
        SEED_FILE,
    )

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
