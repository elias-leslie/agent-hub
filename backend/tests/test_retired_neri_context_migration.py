"""Check exact retirement and referential safety against PostgreSQL."""

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.config import settings
from app.db import _get_async_url
from app.models.agent import Agent
from app.models.prompt import AgentPrompt, Prompt, PromptRevision
from app.services.owned_prompt_service import sync_agent_system_prompt
from scripts.seed_agents import seed_agents


def _migration():
    path = Path(__file__).parents[1] / "alembic/versions/h3f4e5d6c7b8_remove_retired_neri_context.py"
    spec = importlib.util.spec_from_file_location("retired_neri_context", path)
    assert spec and spec.loader
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def _create_tables(connection):
    statements = (
        "CREATE TEMP TABLE agents (id integer PRIMARY KEY, slug text UNIQUE, name text, system_prompt text)",
        """CREATE TEMP TABLE prompts (
            id integer PRIMARY KEY, slug text UNIQUE, name text,
            owner_agent_id integer REFERENCES agents(id) ON DELETE CASCADE
        )""",
        """CREATE TEMP TABLE agent_prompts (
            id integer PRIMARY KEY,
            agent_id integer REFERENCES agents(id) ON DELETE CASCADE,
            prompt_id integer REFERENCES prompts(id) ON DELETE CASCADE
        )""",
        """CREATE TEMP TABLE agent_versions (
            id integer PRIMARY KEY, agent_id integer REFERENCES agents(id) ON DELETE CASCADE
        )""",
        """CREATE TEMP TABLE persona (
            id integer PRIMARY KEY, agent_id integer REFERENCES agents(id) ON DELETE CASCADE
        )""",
        """CREATE TEMP TABLE prompt_revisions (
            id integer PRIMARY KEY, prompt_id integer REFERENCES prompts(id) ON DELETE SET NULL,
            content text
        )""",
    )
    for statement in statements:
        await connection.execute(text(statement))
    await connection.execute(text("""
        INSERT INTO agents VALUES
            (1, 'neri-local-candidate', 'Neri Local Candidate', 'retired local mirror'),
            (2, 'neri-orchestrator', 'Neri Orchestrator', 'retired cadence mirror'),
            (3, 'neri-hunter', 'Neri Hunter', 'hunter'),
            (4, 'neri-reporter', 'Neri Reporter', 'reporter'),
            (5, 'neri-reviewer', 'Neri Reviewer', 'reviewer'),
            (6, 'other', 'Other', 'unrelated'),
            (7, 'neri-orchestrator-backup', 'Unrelated Prefix Match', 'preserved')
    """))
    await connection.execute(text("""
        INSERT INTO prompts VALUES
            (1, 'neri-local-candidate-system-prompt', 'Neri Local Candidate System Prompt', 1),
            (2, 'neri-orchestrator-system-prompt', 'Neri Orchestrator System Prompt', 2),
            (3, 'neri-local-worker-routing', 'Neri Local Worker Routing', NULL),
            (4, 'neri-hunter-system-prompt', 'Neri Hunter System Prompt', 3),
            (5, 'neri-reporter-system-prompt', 'Neri Reporter System Prompt', 4),
            (6, 'neri-reviewer-system-prompt', 'Neri Reviewer System Prompt', 5),
            (7, 'neri-project-operating-policy', 'Neri Project Policy', NULL),
            (8, 'other', 'Other Prompt', 6),
            (9, 'neri-local-worker-routing-extra', 'Unrelated Prefix Match', 6)
    """))
    await connection.execute(text("""
        INSERT INTO agent_prompts
        SELECT id, CASE WHEN id = 3 THEN 2 ELSE COALESCE(owner_agent_id, 6) END, id FROM prompts
    """))
    await connection.execute(text("""
        INSERT INTO agent_prompts VALUES (10, 3, 3), (11, 2, 7), (12, 6, 7)
    """))
    await connection.execute(text("INSERT INTO agent_versions VALUES (1, 1), (2, 2), (3, 3)"))
    await connection.execute(text("INSERT INTO persona VALUES (1, 6)"))
    await connection.execute(text("""
        INSERT INTO prompt_revisions VALUES
            (1, 1, 'retired audit'), (2, 2, 'retired audit'), (3, 3, 'retired audit'),
            (4, 4, 'preserved audit')
    """))


def _apply(migration, connection):
    with Operations.context(MigrationContext.configure(connection)):
        migration.upgrade()


def _test_engine():
    url = _get_async_url(settings.agent_hub_db_url)
    assert make_url(url).database == "agent_hub_test"
    return create_async_engine(url)


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("routing_already_removed", [False, True])
async def test_retirement_is_exact_repeatable_and_preserves_retained_context(routing_already_removed):
    migration = _migration()
    engine = _test_engine()
    try:
        async with engine.connect() as connection:
            await _create_tables(connection)
            if routing_already_removed:
                await connection.execute(text("DELETE FROM prompts WHERE id = 3"))
            await connection.run_sync(lambda sync: _apply(migration, sync))
            await connection.run_sync(lambda sync: _apply(migration, sync))
            assert (await connection.execute(text("SELECT id FROM agents ORDER BY id"))).scalars().all() == [3, 4, 5, 6, 7]
            assert (await connection.execute(text("SELECT id FROM prompts ORDER BY id"))).scalars().all() == [4, 5, 6, 7, 8, 9]
            assert (await connection.execute(text("SELECT id FROM agent_prompts ORDER BY id"))).scalars().all() == [4, 5, 6, 7, 8, 9, 12]
            assert (await connection.execute(text("SELECT id FROM agent_versions"))).scalars().all() == [3]
            assert (await connection.execute(text("SELECT id FROM persona"))).scalars().all() == [1]
            assert (await connection.execute(text("SELECT prompt_id, content FROM prompt_revisions ORDER BY id"))).all() == [
                (None, "retired audit"), (None, "retired audit"), (None, "retired audit"),
                (4, "preserved audit"),
            ]
            await connection.rollback()
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize("drift", ["agent_name", "prompt_name", "owned_prompt", "persona"])
async def test_retirement_stops_before_deleting_unexpected_data(drift):
    migration = _migration()
    engine = _test_engine()
    try:
        async with engine.connect() as connection:
            await _create_tables(connection)
            statements = {
                "agent_name": "UPDATE agents SET name = 'Owner replacement' WHERE id = 1",
                "prompt_name": "UPDATE prompts SET name = 'Owner replacement' WHERE id = 3",
                "owned_prompt": "UPDATE prompts SET owner_agent_id = 1 WHERE id = 8",
                "persona": "UPDATE persona SET agent_id = 1 WHERE id = 1",
            }
            await connection.execute(text(statements[drift]))
            with pytest.raises(RuntimeError, match=r"identity changed|unexpected"):
                await connection.run_sync(lambda sync: _apply(migration, sync))
            assert (await connection.execute(text("SELECT count(*) FROM agents"))).scalar_one() == 7
            assert (await connection.execute(text("SELECT count(*) FROM prompts"))).scalar_one() == 9
            assert (await connection.execute(text("SELECT count(*) FROM agent_prompts"))).scalar_one() == 12
            assert (await connection.execute(text("SELECT count(*) FROM agent_versions"))).scalar_one() == 3
            await connection.rollback()
    finally:
        await engine.dispose()


def test_downgrade_cannot_recreate_retired_context():
    with pytest.raises(RuntimeError, match="intentionally not recreated"):
        _migration().downgrade()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_managed_seed_replay_after_upgrade_cannot_restore_retired_context():
    migration = _migration()
    engine = _test_engine()
    try:
        async with engine.connect() as connection:
            # Current models supply the seed schema and its real foreign keys.
            # Temporary SERIAL columns create private sequences automatically.
            for model in (Agent, Prompt, AgentPrompt, PromptRevision):
                statement = str(CreateTable(model.__table__).compile(dialect=connection.dialect))
                await connection.execute(text(statement.replace("CREATE TABLE", "CREATE TEMP TABLE", 1)))
            await connection.execute(text("CREATE TEMP TABLE persona (id integer, agent_id integer)"))
            async with AsyncSession(bind=connection, expire_on_commit=False) as db:
                retired = []
                for slug, name in migration._AGENTS.items():
                    agent = Agent(
                        slug=slug, name=name, system_prompt="retired mirror",
                        primary_model_id="codex/gpt-6.1-sol", is_active=True,
                    )
                    db.add(agent)
                    await db.flush()
                    await sync_agent_system_prompt(db, agent=agent, system_prompt=agent.system_prompt)
                    retired.append(agent)
                routing = Prompt(
                    slug="neri-local-worker-routing", name="Neri Local Worker Routing",
                    content="retired routing", is_global=False, enabled=True,
                )
                db.add(routing)
                await db.flush()
                db.add(AgentPrompt(agent_id=retired[1].id, prompt_id=routing.id, role="system", priority=50))
                await db.flush()
                await connection.run_sync(lambda sync: _apply(migration, sync))
                db.expunge_all()
                assert await seed_agents(db) > 0
                assert await seed_agents(db) == 0
                assert (await db.execute(text(
                    "SELECT slug FROM agents WHERE slug LIKE 'neri-%' ORDER BY slug"
                ))).scalars().all() == ["neri-hunter", "neri-reporter", "neri-reviewer"]
                assert (await db.execute(text(
                    "SELECT slug FROM prompts WHERE slug LIKE 'neri-%' ORDER BY slug"
                ))).scalars().all() == [
                    "neri-hunter-system-prompt", "neri-reporter-system-prompt", "neri-reviewer-system-prompt",
                ]
                assert (await db.execute(text(
                    "SELECT count(*) FROM agent_prompts ap "
                    "JOIN prompts p ON p.id=ap.prompt_id WHERE p.slug LIKE 'neri-%'"
                ))).scalar_one() == 3
                await db.rollback()
    finally:
        await engine.dispose()
