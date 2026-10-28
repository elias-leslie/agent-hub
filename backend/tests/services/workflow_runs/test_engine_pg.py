"""Workflow run engine against PostgreSQL (rolled-back throwaway schema) with the faux executor."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import Session, SessionEvent, WorkflowStep
from app.services.workflow_runs import engine as engine_module
from app.services.workflow_runs.engine import (
    EngineDeps,
    WorkflowRunError,
    advance_run,
    create_run,
    get_run_view,
    recover_stale_steps,
    resume_run,
)
from app.services.workflow_runs.executors import FauxAction, FauxExecutor
from app.services.workflow_runs.policy import Unavailable
from app.services.workflow_runs.schemas import OwnerDecision, RunDefinition, StepTestHooks

pytestmark = pytest.mark.integration

OPUS, CODEX, OPUS_OLD = "claude-opus-5-5", "codex/gpt-5.6-sol-daybreak-blue", "claude-opus-4-8"
EXAMPLES = Path(__file__).resolve().parents[4] / "docs/examples/workflows"
NOW = 2_000_000_000.0


@pytest_asyncio.fixture
async def pg_db() -> AsyncGenerator[AsyncSession]:
    configured = os.environ.get("TEST_AGENT_HUB_DB_URL")
    if not configured:
        pytest.skip("TEST_AGENT_HUB_DB_URL is required")
    url = make_url(configured).set(drivername="postgresql+asyncpg")
    assert url.database and url.database.endswith("_test")
    engine = create_async_engine(url)
    schema = f"workflow_runs_{uuid4().hex}"
    async with engine.connect() as connection:
        transaction = await connection.begin()
        await connection.execute(text(f"CREATE SCHEMA {schema}"))
        await connection.execute(text(f"SET LOCAL search_path TO {schema}"))

        def create_tables(sync_connection: Any) -> None:
            for table in (Session.__table__, SessionEvent.__table__, WorkflowStep.__table__):
                for column in table.columns:
                    if isinstance(column.type, Enum):
                        column.type.create(sync_connection, checkfirst=True)
                sync_connection.execute(CreateTable(table, include_foreign_key_constraints=[]))

        await connection.run_sync(create_tables)
        async with AsyncSession(
            bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
        ) as session:
            yield session
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    for args in (["init", "-q", "-b", "main"], ["commit", "-q", "--allow-empty", "-m", "base"]):
        subprocess.run(["git", *args], cwd=path, check=True, env=env)
    return path


class World:
    """Everything a test controls: agent chains, availability, cooldown trips and the faux script."""

    def __init__(self, pg_db: AsyncSession, faux: FauxExecutor) -> None:
        self.chains: dict[str, list[str]] = {}
        self.unavailable: dict[str, Unavailable] = {}
        self.tripped: list[tuple[str, float, str]] = []
        self.clock = NOW
        self.faux = faux

        @asynccontextmanager
        async def factory() -> AsyncGenerator[AsyncSession]:
            yield pg_db

        async def resolve(_db: AsyncSession, definition: dict[str, Any]) -> list[str]:
            return list(self.chains[definition["agent_slug"]])

        async def availability(models: list[str]) -> dict[str, Unavailable]:
            return {m: self.unavailable[m] for m in models if m in self.unavailable}

        async def trip(provider: str, seconds: float, signature: str) -> None:
            self.tripped.append((provider, seconds, signature))
            for model in (OPUS, OPUS_OLD) if provider == "claude" else (CODEX,):
                self.unavailable[model] = Unavailable("cooldown", seconds)

        async def thinking(_slug: str) -> str | None:
            return "medium"

        async def context(**_kw: Any) -> tuple[str, str]:
            return "", "ok"

        self.deps = EngineDeps(
            session_factory=factory,
            get_executor=lambda _kind: self.faux,
            resolve_chain=resolve,
            availability=availability,
            trip_cooldown=trip,
            provider_of=lambda m: "codex" if m.startswith("codex/") else "claude",
            context_provider=context,
            agent_thinking_level=thinking,
            owner_only_categories=lambda: {"reasoning_extraction", "frontier_llm"},
            clock=lambda: self.clock,
        )

    async def run_to_stop(self, run_id: str, limit: int = 20) -> dict[str, Any]:
        for _ in range(limit):
            result = await advance_run(run_id, deps=self.deps)
            if result["next"] != "continue":
                return result
        raise AssertionError("run did not stop")


@pytest.fixture
def world_factory(pg_db: AsyncSession, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    class Settings:
        runs_root = tmp_path / "runs"

    monkeypatch.setattr(engine_module, "get_workflow_run_settings", lambda: Settings)

    def make(script: dict[str, list[FauxAction]] | None = None) -> World:
        return World(pg_db, FauxExecutor(script))

    return make


def example(name: str, repo: Path | None, **extra: Any) -> RunDefinition:
    data = json.loads((EXAMPLES / f"{name}.json").read_text())
    data["policy"] = {"heartbeat_interval_seconds": 3600, **extra.pop("policy", {})}
    for step in data["steps"]:
        step["executor"] = "faux"
    if repo is not None:
        data["repo_path"] = str(repo)
    data.update(extra)
    return RunDefinition(**data)


async def view_of(db: AsyncSession, run_id: str) -> dict[str, Any]:
    view = await get_run_view(db, run_id)
    assert view is not None
    return view


def chains(world: World) -> None:
    world.chains.update(
        {slug: [OPUS, CODEX, OPUS_OLD] for slug in ("planner", "coder", "reviewer")}
    )


async def test_example_run_with_injected_refusal_takes_over_and_opus_returns(
    pg_db, repo, world_factory
) -> None:
    world = world_factory(
        {
            "implement": [
                FauxAction(
                    "refuse",
                    category="cyber",
                    write={"feature.py": "print('half')\n"},
                    progress=["read export.py", "wrote feature.py"],
                ),
                FauxAction("success", write={"feature.py": "print('done')\n"}),
            ],
        }
    )
    chains(world)
    run_id, created = await create_run(
        pg_db, example("plan-implement-review-fix", repo), deps=world.deps
    )
    assert created
    assert (await world.run_to_stop(run_id))["reason"] == "completed"

    view = await view_of(pg_db, run_id)
    assert view["state"] == "completed"
    steps = {s["key"]: s for s in view["steps"]}
    assert all(
        s["status"] == "completed" and s["handoff"]["summary"] and s["checkpoint_sha"]
        for s in steps.values()
    )

    implement = steps["implement"]
    assert implement["hops"] == [
        {"from_model": OPUS, "to_model": CODEX, "category": "cyber", "kind": "refused"}
    ]
    first, second = implement["attempt_history"]
    assert (first["status"], first["requested_model"], first["effective_model"]) == (
        "failed",
        OPUS,
        OPUS,
    )
    assert (second["status"], second["requested_model"], second["effective_model"]) == (
        "completed",
        OPUS,
        CODEX,
    )
    assert (
        second["fallback_used"] is True
        and "refused (cyber) on claude-opus-5-5" in second["fallback_reason"]
    )
    assert second["served_models"] == [CODEX]
    assert implement["answered_by"] == [CODEX]

    # Takeover kept the worktree and told the new model what was left behind; the refused turn is not resent.
    takeover = next(c for c in world.faux.calls if c["step"] == "implement" and c["model"] == CODEX)
    assert "Partial progress" in takeover["packet"] and "feature.py" in takeover["packet"]
    assert (
        "wrote feature.py" in takeover["packet"]
        and "takeover: refused (cyber)" in takeover["packet"]
    )
    # Later steps start from their own primary again.
    assert [c["model"] for c in world.faux.calls if c["step"] in ("review", "fix")] == [OPUS, OPUS]
    assert view["refusals"] == {"cyber": 1}
    assert (Path(view["worktree"]) / "feature.py").read_text() == "print('done')\n"
    review = next(c for c in world.faux.calls if c["step"] == "review")
    assert "implement" in review["packet"] and "Partial progress" not in review["packet"]


async def test_chain_exhaustion_goes_to_the_owner_with_each_model_tried_once(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("refuse", category="cyber")]})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    result = await world.run_to_stop(run_id)
    assert (result["run_state"], result["reason"]) == ("needs_owner", "chain_exhausted")
    assert [c["model"] for c in world.faux.calls] == [OPUS, CODEX, OPUS_OLD]
    view = await view_of(pg_db, run_id)
    assert (
        view["steps"][0]["status"] == "needs_owner" and view["pause"]["reason"] == "chain_exhausted"
    )

    # The owner retries the step on a model of their choice; the run continues to the end.
    world.faux.script["plan"] = [FauxAction("success")]
    resumed = await resume_run(
        pg_db, run_id, OwnerDecision(action="retry", model=CODEX), deps=world.deps
    )
    assert resumed["state"] == "running"
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert world.faux.calls[3]["model"] == CODEX
    with pytest.raises(WorkflowRunError, match="not waiting for the owner"):
        await resume_run(pg_db, run_id, OwnerDecision(action="skip"), deps=world.deps)


@pytest.mark.parametrize("enabled", [False, True])
async def test_step_test_hooks_reach_the_executor_only_when_enabled(
    pg_db, repo, world_factory, enabled
) -> None:
    world = world_factory({})
    chains(world)
    world.deps.test_hooks_on = lambda: enabled
    seen: list[Any] = []
    inner = world.faux.run

    async def capture(packet, *args, **kwargs):
        seen.append(packet.test_hooks)
        assert packet.thinking_level == "medium" and packet.attempt.agent_slug
        return await inner(packet, *args, **kwargs)

    world.faux.run = capture
    definition = example("plan-implement-review-fix", repo)
    definition.steps[0].test_hooks = StepTestHooks(refuse_after_turn=2, refusal_category="bio")
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await advance_run(run_id, deps=world.deps)
    hooks = {"refuse_after_turn": 2, "refusal_category": "bio"}
    assert seen[0] == (hooks if enabled else None)


async def test_owner_only_refusal_category_is_not_handed_to_the_chain(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("refuse", category="reasoning_extraction")]})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    result = await world.run_to_stop(run_id)
    assert result["reason"] == "owner_only_category" and len(world.faux.calls) == 1
    failed = await resume_run(pg_db, run_id, OwnerDecision(action="fail"), deps=world.deps)
    view = await view_of(pg_db, run_id)
    assert failed["state"] == "failed" and view["steps"][0]["status"] == "refused"
    assert {s["status"] for s in view["steps"][1:]} == {"skipped"}


async def test_usage_limit_trips_shared_cooldown_and_resumes_after_reset(
    pg_db, repo, world_factory
) -> None:
    resets = int(NOW) + 600
    world = world_factory({"research": [FauxAction("usage_limit", resets_at=resets)]})
    world.chains["researcher"] = world.chains["verifier"] = [OPUS, CODEX]
    world.unavailable[CODEX] = Unavailable("cooldown", 660)  # the next model is cooling down too
    run_id, _ = await create_run(pg_db, example("research-report-factcheck", repo), deps=world.deps)
    result = await world.run_to_stop(run_id)
    assert [t[0] for t in world.tripped] == ["claude"] and world.tripped[0][1] == 600.0
    assert result["reason"] == "usage_limit_wait"
    view = await view_of(pg_db, run_id)
    assert (
        view["pause"]["reason"] == "usage_limit_wait" and view["pause"]["resume_after"] == NOW + 600
    )

    assert await recover_stale_steps(world.deps) == []  # still cooling down
    world.clock = NOW + 700
    world.unavailable.clear()
    world.faux.script["research"] = [FauxAction("success")]
    assert await recover_stale_steps(world.deps) == [run_id]
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    # The limited model is untried again once its limit has reset.
    assert [c["model"] for c in world.faux.calls if c["step"] == "research"] == [OPUS, OPUS]


async def test_every_model_usage_limited_waits_for_the_earliest_reset(
    pg_db, repo, world_factory
) -> None:
    world = world_factory(
        {
            "research": [
                FauxAction("usage_limit", resets_at=int(NOW) + 900),
                FauxAction("usage_limit", resets_at=int(NOW) + 300),
            ]
        }
    )
    world.chains["researcher"] = world.chains["verifier"] = [OPUS, CODEX]
    run_id, _ = await create_run(pg_db, example("research-report-factcheck", repo), deps=world.deps)
    result = await world.run_to_stop(run_id)
    # Both models were tried and both hit a usage limit: wait for the sooner reset, not chain_exhausted.
    assert [c["model"] for c in world.faux.calls] == [OPUS, CODEX]
    assert result["reason"] == "usage_limit_wait"
    view = await view_of(pg_db, run_id)
    assert view["pause"]["reason"] == "usage_limit_wait"
    assert view["pause"]["resume_after"] == NOW + 300


async def test_stale_heartbeat_restarts_from_checkpoint_then_fails_at_the_limit(
    pg_db, repo, world_factory
) -> None:
    world = world_factory(
        {
            "investigate": [FauxAction("success")],
            "reproduce": [FauxAction("success", write={"t.py": "ok\n"})],
        }
    )
    for slug in ("debugger", "tester", "coder", "verifier"):
        world.chains[slug] = [OPUS, CODEX]
    run_id, _ = await create_run(
        pg_db,
        example(
            "investigate-reproduce-fix-verify",
            repo,
            policy={"stale_after_seconds": 100, "restart_limit": 2},
        ),
        deps=world.deps,
    )
    await advance_run(run_id, deps=world.deps)  # investigate done
    # "reproduce" starts (intent committed) and the worker dies mid-effect: nothing else is written.
    _early, intent = await engine_module._commit_intent(run_id, world.deps)
    assert intent is not None and intent.step_key == "reproduce"
    junk = Path((await view_of(pg_db, run_id))["worktree"]) / "half-written.txt"
    junk.write_text("partial")

    assert await recover_stale_steps(world.deps) == []  # heartbeat is fresh
    world.clock += 500
    assert await recover_stale_steps(world.deps) == [run_id]
    step = (await view_of(pg_db, run_id))["steps"][1]
    assert (step["status"], step["restarts"], step["attempts"]) == ("pending", 1, 1)
    assert (
        step["attempt_history"][0]["status"] == "failed"
        and "stale_heartbeat" in step["attempt_history"][0]["error"]
    )

    await advance_run(run_id, deps=world.deps)  # same model, back at the checkpoint
    assert not junk.exists()
    assert world.faux.calls[-1]["model"] == OPUS
    view = await view_of(pg_db, run_id)
    assert view["steps"][1]["status"] == "completed" and view["steps"][1]["attempts"] == 2

    # Next step dies twice: restarts reach the limit and the step ends visibly failed.
    for expected in ("pending", "failed"):
        await engine_module._commit_intent(run_id, world.deps)
        world.clock += 500
        await recover_stale_steps(world.deps)
        view = await view_of(pg_db, run_id)
        assert view["steps"][2]["status"] == expected
    assert view["state"] == "failed" and view["steps"][2]["restarts"] == 2
    assert view["steps"][3]["status"] == "skipped"


async def test_attempt_abandoned_after_recovery_does_not_overwrite_the_step(
    pg_db, repo, world_factory
) -> None:
    world = world_factory()
    world.chains["researcher"] = world.chains["verifier"] = [OPUS, CODEX]
    run_id, _ = await create_run(
        pg_db,
        example("research-report-factcheck", repo, policy={"stale_after_seconds": 100}),
        deps=world.deps,
    )
    _early, intent = await engine_module._commit_intent(run_id, world.deps)
    world.clock += 500
    await recover_stale_steps(world.deps)
    from app.services.workflow_runs.executors import StepResult

    late = await engine_module._commit_outcome(
        run_id,
        intent,
        StepResult("completed", [OPUS], handoff={"summary": "late"}),
        {"summary": "late"},
        "sha",
        None,
        None,
        {},
        {},
        world.deps,
    )
    assert late["reason"] == "attempt_abandoned"
    assert (await view_of(pg_db, run_id))["steps"][0]["status"] == "pending"


async def test_create_run_is_idempotent_on_request_id_and_rejects_unknown_agents(
    pg_db, repo, world_factory
) -> None:
    world = world_factory()
    chains(world)
    definition = example("plan-implement-review-fix", repo)
    first, created = await create_run(pg_db, definition, deps=world.deps)
    again, created_again = await create_run(pg_db, definition, deps=world.deps)
    assert (created, created_again, first == again) == (True, False, True)
    unknown = example("research-report-factcheck", repo)
    with pytest.raises(KeyError):
        await create_run(pg_db, unknown, deps=world.deps)


async def test_run_session_is_a_workflow_session_with_attempt_children(
    pg_db, repo, world_factory
) -> None:
    world = world_factory()
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    await world.run_to_stop(run_id)
    run = await pg_db.get(Session, run_id)
    assert (run.session_type, run.status) == ("workflow", "completed")
    children = (
        await pg_db.execute(
            text("select count(*) from sessions where parent_session_id = :id"), {"id": run_id}
        )
    ).scalar()
    assert children == 4
    events = (
        await pg_db.execute(
            text("select count(*) from session_events where session_id = :id"), {"id": run_id}
        )
    ).scalar()
    assert events >= 8  # started + result per attempt on the run timeline


async def test_list_runs_newest_first_with_counts_usage_and_served_models(
    pg_db, repo, world_factory
) -> None:
    from app.services.workflow_runs.listing import list_runs

    world = world_factory(
        {
            "plan": [FauxAction("refuse", category="cyber"), FauxAction("success")],
            "implement": [FauxAction("substitute", served_model=OPUS_OLD, category="cyber")],
        }
    )
    chains(world)
    first, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    await world.run_to_stop(first)
    second, _ = await create_run(
        pg_db, example("plan-implement-review-fix", repo, request_id="second"), deps=world.deps
    )

    # One test transaction gives both rows the same server clock; separate the start times explicitly.
    for run_id, day in ((first, 1), (second, 2)):
        await pg_db.execute(
            update(Session).where(Session.id == run_id).values(created_at=datetime(2026, 1, day, tzinfo=UTC))
        )

    listing = await list_runs(pg_db, limit=10, offset=0)
    assert listing["total"] == 2
    assert [r["id"] for r in listing["runs"]] == [second, first]
    fresh, done = listing["runs"]
    assert (fresh["state"], fresh["attempt_count"], fresh["total_tokens"], fresh["cost_usd"]) == (
        "running",
        0,
        None,
        None,
    )
    assert fresh["step_total"] == 4 and fresh["step_counts"] == {"pending": 4}
    assert done["state"] == "completed" and done["step_counts"] == {"completed": 4}
    assert done["attempt_count"] == 6 and done["flagged_attempts"] == 3
    assert done["total_tokens"] == 6 * 120 and done["cost_usd"] is None
    assert set(done["served_models"]) == {OPUS, CODEX, OPUS_OLD}

    attempt = (await view_of(pg_db, first))["steps"][0]["attempt_history"][0]
    assert attempt["started_at"] and attempt["finished_at"] >= attempt["started_at"]

    page = await list_runs(pg_db, limit=1, offset=1)
    assert [r["id"] for r in page["runs"]] == [first] and page["total"] == 2


async def test_workflow_runs_endpoints_list_and_paginate(pg_db, repo, world_factory) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.workflow_runs import router
    from app.db import get_db

    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    app = FastAPI()
    app.include_router(router)

    async def override() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = override
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get("/workflow-runs", params={"limit": 5})).json()
        assert [r["id"] for r in body["runs"]] == [run_id] and body["limit"] == 5
        empty = (await client.get("/workflow-runs", params={"offset": 5})).json()
        assert empty["runs"] == [] and empty["total"] == 1
        assert (await client.get("/workflow-runs", params={"limit": 0})).status_code == 422
        assert (await client.get(f"/workflow-runs/{run_id}")).json()["id"] == run_id
