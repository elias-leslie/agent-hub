"""Workflow run engine against PostgreSQL (rolled-back throwaway schema) with the faux executor."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import Enum, make_url, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.models import (
    CostLog,
    Session,
    SessionEvent,
    SubscriptionUsageSnapshot,
    WorkflowStep,
)
from app.services.workflow_runs import engine as engine_module
from app.services.workflow_runs.engine import (
    EngineDeps,
    WorkflowRunError,
    advance_run,
    cancel_run,
    cancel_step,
    create_run,
    get_run_view,
    recover_stale_steps,
    resume_run,
)
from app.services.workflow_runs.executor_common import HarnessProcess, child_env, load_defaults
from app.services.workflow_runs.executors import FauxAction, FauxExecutor, StepResult
from app.services.workflow_runs.live import note_live
from app.services.workflow_runs.policy import Unavailable
from app.services.workflow_runs.processes import MARKER_ENV, identify, read_stat
from app.services.workflow_runs.revisions import add_steps, remove_step, revise_run, revise_step
from app.services.workflow_runs.schemas import (
    AcceptanceCommand,
    AddSteps,
    CancelRequest,
    OwnerDecision,
    RemoveStep,
    RunDefinition,
    RunRevision,
    StepRevision,
    StepTestHooks,
)
from app.services.workflow_runs.workspace import RunWorkspace

pytestmark = pytest.mark.integration

OPUS, CODEX, OPUS_OLD = "claude-opus-5-5", "codex/gpt-5.6-sol-daybreak-blue", "claude-opus-4-8"
EXAMPLES = Path(__file__).resolve().parents[4] / "docs/examples/workflows"
NOW = 2_000_000_000.0
NO_WORK = {"input_tokens": 0, "output_tokens": 0}  # an attempt that failed before the model produced anything


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
            for table in (
                Session.__table__,
                SessionEvent.__table__,
                WorkflowStep.__table__,
                CostLog.__table__,
                SubscriptionUsageSnapshot.__table__,
            ):
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
        # One connection serves the engine's heartbeat and the test's own calls: they take turns.
        self.lock = asyncio.Lock()

        @asynccontextmanager
        async def factory() -> AsyncGenerator[AsyncSession]:
            async with self.lock:
                yield pg_db

        async def resolve(_db: AsyncSession, definition: dict[str, Any]) -> list[str]:
            chain = list(self.chains[definition["agent_slug"]])
            override = definition.get("model_override")
            if override:
                chain = [override, *(m for m in chain if m != override)]
            if definition.get("allowed_models"):
                chain = [m for m in chain if m in definition["allowed_models"]]
            return chain

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

        self.tasks: list[asyncio.Task[dict[str, Any]]] = []
        self.deps = EngineDeps(
            enqueue_advance=self.spawn,
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

    async def spawn(self, run_id: str) -> None:
        """Queue an advance the way the Hatchet task does: it runs beside the others."""

        self.tasks.append(asyncio.create_task(self._advance_then_queue(run_id)))

    async def _advance_then_queue(self, run_id: str) -> dict[str, Any]:
        result = await advance_run(run_id, deps=self.deps)
        if result["next"] == "continue":
            await self.spawn(run_id)
        return result

    async def drive(self, run_id: str, timeout: float = 60) -> list[dict[str, Any]]:
        """Run advances until none is left, as many at once as the run's cap lets them start."""

        await self.spawn(run_id)
        await self.settle(timeout)
        return [task.result() for task in self.tasks]

    async def settle(self, timeout: float = 60) -> None:
        while pending := [t for t in self.tasks if not t.done()]:
            done, _ = await asyncio.wait(pending, timeout=timeout)
            assert done, "advances did not finish"

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
        step["acceptance"] = []  # the examples name project commands (make test) that cannot run here
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
    # A takeover records the model it asked for, not the step's primary.
    assert (second["status"], second["requested_model"], second["effective_model"]) == (
        "completed",
        CODEX,
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

    # restart_limit 2 means two restarts: the third stall ends the step visibly failed.
    for expected, restarts in (("pending", 1), ("pending", 2), ("failed", 2)):
        await engine_module._commit_intent(run_id, world.deps)
        world.clock += 500
        await recover_stale_steps(world.deps)
        view = await view_of(pg_db, run_id)
        assert (view["steps"][2]["status"], view["steps"][2]["restarts"]) == (expected, restarts)
    assert view["state"] == "failed" and "no restart left: 2/2 used" in view["failure"]
    assert view["steps"][3]["status"] == "skipped"
    assert view["limits"]["restart_limit"] == 2


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
    assert (fresh["state"], fresh["attempt_count"], fresh["total_tokens"]) == ("running", 0, None)
    assert fresh["cost"]["unpriced_attempts"] == 0
    assert fresh["step_total"] == 4 and fresh["step_counts"] == {"pending": 4}
    assert done["state"] == "completed" and done["step_counts"] == {"completed": 4}
    assert done["attempt_count"] == 6 and done["flagged_attempts"] == 3
    assert done["total_tokens"] == 6 * 120
    # The test executor reports no price: six unpriced attempts, none summed as zero.
    assert done["cost"]["unpriced_attempts"] == 6
    assert done["cost"]["by_basis"]["unknown"] == {"usd": None, "attempts": 6, "unpriced_attempts": 6}
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


# --- acceptance, attempt caps and per-step effort ---------------------------------------------------

CHECK = "test -f out.txt || { echo 'missing out.txt'; exit 3; }"


def with_acceptance(definition: RunDefinition, *cmds: str | AcceptanceCommand) -> RunDefinition:
    definition.steps[0].acceptance = [
        c if isinstance(c, AcceptanceCommand) else AcceptanceCommand(cmd=c) for c in cmds
    ]
    return definition


async def test_acceptance_passing_completes_the_step_and_records_each_command(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction(write={"out.txt": "ok\n"})]})
    chains(world)
    definition = with_acceptance(
        example("plan-implement-review-fix", repo), CHECK, AcceptanceCommand(cmd="echo fine", timeout_s=5)
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    view = await view_of(pg_db, run_id)
    plan = view["steps"][0]
    (attempt,) = plan["attempt_history"]
    assert [(r["cmd"], r["exit_code"], r["passed"]) for r in attempt["acceptance"]] == [
        (CHECK, 0, True),
        ("echo fine", 0, True),
    ]
    assert attempt["acceptance"][1]["output_tail"] == "fine" and attempt["acceptance"][1]["duration_s"] >= 0
    assert plan["status"] == "completed" and plan["checkpoint_sha"] and plan["acceptance_failures"] == 0
    assert [a["cmd"] for a in plan["acceptance"]] == [CHECK, "echo fine"]
    # Steps without acceptance commands behave as before.
    assert view["steps"][1]["attempt_history"][0]["acceptance"] is None


async def test_failed_acceptance_retries_with_the_failing_output_then_passes(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction(), FauxAction(write={"out.txt": "ok\n"})]})
    chains(world)
    definition = with_acceptance(example("plan-implement-review-fix", repo), CHECK)
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"

    plan = (await view_of(pg_db, run_id))["steps"][0]
    first, second = plan["attempt_history"]
    assert (first["status"], first["acceptance"][0]["exit_code"], first["decision"]["reason"]) == (
        "failed",
        3,
        "acceptance_failed",
    )
    assert "missing out.txt" in first["acceptance"][0]["output_tail"]
    assert (second["status"], second["acceptance"][0]["passed"]) == ("completed", True)
    assert plan["acceptance_failures"] == 1 and plan["attempts"] == 2
    # The retry is the same model, in the same worktree, and its packet carries the failing output.
    retry = [c for c in world.faux.calls if c["step"] == "plan"][1]
    assert retry["model"] == OPUS
    assert "acceptance failed" in retry["packet"] and "missing out.txt" in retry["packet"]
    assert "exit code 3" in retry["packet"]


async def test_acceptance_that_never_passes_fails_the_step_at_the_retry_limit(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction()]})
    chains(world)
    definition = with_acceptance(example("plan-implement-review-fix", repo), CHECK)
    definition.policy = {"heartbeat_interval_seconds": 3600, "acceptance_retry_limit": 2}
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    result = await world.run_to_stop(run_id)
    assert (result["run_state"], result["reason"]) == ("failed", "acceptance_retry_limit")
    view = await view_of(pg_db, run_id)
    plan = view["steps"][0]
    assert (plan["status"], plan["attempts"], plan["acceptance_failures"]) == ("failed", 3, 3)
    assert "plan: acceptance_retry_limit" in view["failure"]
    assert view["limits"]["acceptance_retry_limit"] == 2 and plan["attempt_limit"] == view["limits"]["max_total_attempts"]
    assert {s["status"] for s in view["steps"][1:]} == {"skipped"}


async def test_acceptance_timeout_and_unrunnable_command_count_as_failures(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    definition = with_acceptance(
        example("plan-implement-review-fix", repo), AcceptanceCommand(cmd="sleep 30", timeout_s=1)
    )
    definition.policy = {"heartbeat_interval_seconds": 3600, "acceptance_retry_limit": 0}
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.run_to_stop(run_id)
    (attempt,) = (await view_of(pg_db, run_id))["steps"][0]["attempt_history"]
    (result,) = attempt["acceptance"]
    assert (result["timed_out"], result["exit_code"], result["passed"]) == (True, None, False)


async def test_stored_runs_with_bare_string_acceptance_still_load_and_run(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction(write={"out.txt": "x"})]})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    step = (await engine_module._steps(pg_db, run_id))[0]
    step.definition = {**step.definition, "acceptance": ["test -f out.txt"]}  # the pre-object shape
    await pg_db.commit()
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert (await view_of(pg_db, run_id))["steps"][0]["attempt_history"][0]["acceptance"][0]["passed"]


async def test_usage_limit_cycles_and_owner_retries_stop_at_the_attempt_caps(
    pg_db, repo, world_factory
) -> None:
    # An attempt that used no tokens made no progress, so every wait after it counts toward the pause.
    limit = FauxAction("usage_limit", resets_at=int(NOW) + 60, usage=NO_WORK)
    world = world_factory({"plan": [limit]})
    world.chains.update({slug: [OPUS] for slug in ("planner", "coder", "reviewer")})
    definition = example(
        "plan-implement-review-fix",
        repo,
        policy={"max_unproductive_usage_limit_resumes": 1, "max_total_attempts": 4},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)

    async def pass_the_reset() -> bool:
        world.clock += 120
        world.unavailable.clear()
        return run_id in await recover_stale_steps(world.deps)

    async def until_the_owner_is_needed() -> dict[str, Any]:
        """Wait out each reset the way the recovery loop does, until the step pauses for the owner."""
        for _ in range(10):
            stop = await world.run_to_stop(run_id)
            if stop["reason"] != "usage_limit_wait":
                return stop
            assert await pass_the_reset()
        raise AssertionError("the usage-limit waits never paused")

    async def plan() -> dict[str, Any]:
        return (await view_of(pg_db, run_id))["steps"][0]

    assert (await until_the_owner_is_needed())["reason"] == "usage_limit_resume_limit"
    assert not await pass_the_reset()  # no more automatic resumes: the owner decides
    view = await view_of(pg_db, run_id)
    assert view["steps"][0]["usage_limit_resumes"] == 1 and view["state"] == "needs_owner"
    first_round = (await plan())["attempts"]

    await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)  # fresh counters
    assert (await until_the_owner_is_needed())["reason"] == "usage_limit_resume_limit"
    assert (await plan())["attempts"] > first_round
    # Run the plain owner retries up to the cap.
    while (await plan())["attempts"] < 4:
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
        await until_the_owner_is_needed()
    assert (await plan())["attempts"] == 4 == (await view_of(pg_db, run_id))["limits"]["max_total_attempts"]
    with pytest.raises(WorkflowRunError, match="extra_attempts") as raised:
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
    assert raised.value.code == "attempt_limit"
    # The owner can raise this step's cap explicitly; who asked and how many is kept and shown.
    await resume_run(
        pg_db,
        run_id,
        OwnerDecision(action="retry", extra_attempts=2, note="the reset is close"),
        requested_by="client-7",
        request_source="dashboard",
        deps=world.deps,
    )
    granted = await plan()
    assert granted["attempt_limit"] == 6 and granted["extra_attempts"]["total"] == 2
    (grant,) = granted["extra_attempts"]["grants"]
    assert (grant["count"], grant["requested_by"], grant["request_source"]) == (2, "client-7", "dashboard")
    await until_the_owner_is_needed()
    while (await plan())["attempts"] < 6:  # the granted attempts run as ordinary owner retries
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
        await until_the_owner_is_needed()
    assert (await plan())["attempts"] == 6  # the two granted attempts ran, then the cap
    with pytest.raises(WorkflowRunError) as capped:  # automatic loops stay capped; each grant is spent once
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
    assert capped.value.code == "attempt_limit"
    # The owner can still end the run.
    ended = await resume_run(pg_db, run_id, OwnerDecision(action="fail"), deps=world.deps)
    assert ended["state"] == "failed"
    assert len(world.faux.calls) == 6


async def test_usage_limit_waits_after_progress_never_pause_and_the_count_resets(
    pg_db, repo, world_factory
) -> None:
    """Waiting costs nothing: only waits in a row with no new tokens since the previous resume count."""

    idle = FauxAction("usage_limit", resets_at=int(NOW) + 60, usage=NO_WORK)
    worked = FauxAction("usage_limit", resets_at=int(NOW) + 60)  # the default usage carries tokens
    world = world_factory({"plan": [idle, idle, worked, idle, idle, idle]})
    world.chains.update({slug: [OPUS] for slug in ("planner", "coder", "reviewer")})
    definition = example(
        "plan-implement-review-fix",
        repo,
        policy={"max_unproductive_usage_limit_resumes": 2, "max_total_attempts": 12},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)

    async def pass_the_reset() -> bool:
        world.clock += 120
        world.unavailable.clear()
        return run_id in await recover_stale_steps(world.deps)

    counts = []
    for _attempt in range(1, 6):
        assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_wait"
        counts.append((await view_of(pg_db, run_id))["steps"][0]["unproductive_resumes"])
        assert await pass_the_reset()
    # idle, idle, worked (resets), idle, idle: five waits, never a pause. Two idle ones before it would have paused
    # at the third attempt had the count not reset.
    assert counts == [1, 2, 0, 1, 2]
    assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_resume_limit"  # attempt 6, idle again
    view = await view_of(pg_db, run_id)
    assert view["state"] == "needs_owner" and view["steps"][0]["usage_limit_resumes"] == 5


async def test_usage_limit_cycling_alone_fails_the_step_at_max_total_attempts(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("usage_limit", resets_at=int(NOW) + 60)]})
    world.chains.update({slug: [OPUS] for slug in ("planner", "coder", "reviewer")})
    definition = example(
        "plan-implement-review-fix",
        repo,
        policy={"max_unproductive_usage_limit_resumes": 1, "max_total_attempts": 3},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    for _ in range(10):
        result = await world.run_to_stop(run_id)
        if result["reason"] == "max_total_attempts":
            break
        world.clock += 120
        world.unavailable.clear()
        await recover_stale_steps(world.deps)
    view = await view_of(pg_db, run_id)
    assert (view["state"], view["steps"][0]["attempts"]) == ("failed", 3)
    assert "plan: max_total_attempts" in view["failure"] and len(world.faux.calls) == 3


async def test_refusing_chain_and_owner_retry_stop_at_a_step_max_attempts(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("refuse", category="cyber")]})
    chains(world)
    definition = example("plan-implement-review-fix", repo)
    definition.steps[0].max_attempts = 2
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    result = await world.run_to_stop(run_id)
    # Refusals used to ignore max_attempts; now the second refusal ends the step instead of a third hop.
    assert (result["run_state"], len(world.faux.calls)) == ("failed", 2)
    view = await view_of(pg_db, run_id)
    assert view["steps"][0]["attempt_limit"] == 2 and "max_attempts" in view["failure"]


async def test_step_effort_overrides_the_agent_thinking_level(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    seen: list[tuple[str, str | None]] = []
    inner = world.faux.run

    async def capture(packet, *args, **kwargs):
        seen.append((packet.step_key, packet.thinking_level))
        return await inner(packet, *args, **kwargs)

    world.faux.run = capture
    definition = example("plan-implement-review-fix", repo)
    definition.steps[1].effort = "xhigh"
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.run_to_stop(run_id)
    # The test agent's thinking level is "medium"; only the step that names an effort differs.
    assert dict(seen) == {"plan": "medium", "implement": "xhigh", "review": "medium", "fix": "medium"}
    assert (await view_of(pg_db, run_id))["steps"][1]["effort"] == "xhigh"


async def test_takeover_attempt_records_the_model_it_asked_for(pg_db, repo, world_factory) -> None:
    world = world_factory({"plan": [FauxAction("refuse", category="cyber"), FauxAction()]})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    await world.run_to_stop(run_id)
    first, second = (await view_of(pg_db, run_id))["steps"][0]["attempt_history"]
    assert (first["requested_model"], second["requested_model"]) == (OPUS, CODEX)
    assert second["effective_model"] == CODEX and second["fallback_used"] is True
    row = await pg_db.get(Session, second["session_id"])
    assert row.model == CODEX and row.provider_metadata["requested_model"] == CODEX


# --- usage totals by cost basis, cost rows and acceptance on a substituted answer ---------------------


def priced(usd: float | None, basis: str, source: str | None = "provider_reported") -> dict[str, Any]:
    return {
        "input_tokens": 1000,
        "output_tokens": 100,
        "total_tokens": 1100,
        "cost_usd": usd,
        "cost_basis": basis,
        "cost_source": source,
    }


async def cost_rows(db: AsyncSession) -> list[CostLog]:
    return list((await db.execute(select(CostLog).order_by(CostLog.id))).scalars())


async def test_totals_split_attempts_by_basis_and_cost_rows_are_written_once_per_harness_attempt(
    pg_db, repo, world_factory
) -> None:
    from app.services.workflow_runs.listing import list_runs

    world = world_factory(
        {
            "plan": [FauxAction(usage=priced(0.5, "metered"))],
            "implement": [FauxAction(usage=priced(2.0, "subscription_equiv"))],
            "review": [FauxAction(usage=priced(None, "subscription_equiv", None))],
            "fix": [FauxAction(usage=priced(1.0, "subscription_equiv", "catalog_estimate"))],
        }
    )
    chains(world)
    definition = example("plan-implement-review-fix", repo)
    for step in definition.steps:
        step.executor = "pi"  # a harness executor, so each attempt writes its cost row (the faux runs it)
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"

    view = await view_of(pg_db, run_id)
    by = view["usage_totals"]["cost"]["by_basis"]
    assert (by["metered"]["usd"], by["subscription_equiv"]["usd"]) == (0.5, 3.0)
    assert by["subscription_equiv"] == {"usd": 3.0, "attempts": 3, "unpriced_attempts": 1}
    assert by["unknown"]["attempts"] == 0 and view["usage_totals"]["cost"]["estimated_attempts"] == 1
    assert view["usage_totals"]["total_tokens"] == 4 * 1100
    costs = [a["cost"] for s in view["steps"] for a in s["attempt_history"]]
    assert costs[0] == {"usd": 0.5, "basis": "metered", "source": "provider_reported"}
    assert costs[2] == {"usd": None, "basis": "subscription_equiv", "source": None}

    listed = (await list_runs(pg_db, limit=5, offset=0))["runs"][0]
    assert listed["cost"] == view["usage_totals"]["cost"] and listed["total_tokens"] == 4 * 1100

    rows = await cost_rows(pg_db)
    assert len(rows) == 4  # one per attempt
    assert [(r.billing_mode, r.cost_usd, r.api_equiv_usd) for r in rows] == [
        ("metered", 0.5, None),
        ("subscription", 0.0, 2.0),
        ("subscription", 0.0, None),
        ("subscription", 0.0, 1.0),
    ]
    assert {r.session_id for r in rows} == {
        a["session_id"] for s in view["steps"] for a in s["attempt_history"]
    }
    # Advancing a finished run writes nothing more.
    await advance_run(run_id, deps=world.deps)
    assert len(await cost_rows(pg_db)) == 4


async def test_faux_and_agent_hub_attempts_write_no_cost_rows(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    await world.run_to_stop(run_id)
    assert await cost_rows(pg_db) == []


async def test_acceptance_failure_on_a_substituted_answer_retries_the_requested_model(
    pg_db, repo, world_factory
) -> None:
    world = world_factory(
        {
            "plan": [
                FauxAction("substitute", served_model=CODEX, write={}),
                FauxAction(write={"out.txt": "ok\n"}),
            ]
        }
    )
    chains(world)
    definition = with_acceptance(example("plan-implement-review-fix", repo), CHECK)
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    plan = (await view_of(pg_db, run_id))["steps"][0]
    first, second = plan["attempt_history"]
    assert (first["served_models"], first["decision"]["reason"]) == ([CODEX], "acceptance_failed")
    assert second["requested_model"] == OPUS  # not the substitute the first attempt was answered by
    assert [c["model"] for c in world.faux.calls if c["step"] == "plan"] == [OPUS, OPUS]


async def test_acceptance_retry_takes_the_next_model_when_the_requested_one_is_no_longer_eligible(
    pg_db, repo, world_factory
) -> None:
    world = world_factory(
        {"plan": [FauxAction("substitute", served_model=CODEX), FauxAction(write={"out.txt": "ok\n"})]}
    )
    chains(world)
    plain_availability = world.deps.availability

    async def cooling_after_first_attempt(models: list[str]) -> dict[str, Unavailable]:
        found = await plain_availability(models)
        if world.faux.calls and OPUS in models:
            found[OPUS] = Unavailable("cooldown", 600.0)
        return found

    world.deps.availability = cooling_after_first_attempt
    definition = with_acceptance(example("plan-implement-review-fix", repo), CHECK)
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert [c["model"] for c in world.faux.calls if c["step"] == "plan"] == [OPUS, CODEX]


# --- the subscription usage page prefers the newest window reading ----------------------------------


def window_attempt(provider: str, finished_at: float, windows: dict[str, float], **extra: Any) -> Session:
    usage = {"input_tokens": 1, "rate_limit_windows": windows, **extra}
    return Session(
        id=str(uuid4()),
        project_id="p",
        provider=provider,
        model="m",
        status="completed",
        session_type="agent",
        request_source="workflow_run",
        provider_metadata={"workflow_attempt": {"usage": usage, "finished_at": finished_at, "step_key": "s"}},
    )


async def test_workflow_window_readings_beat_an_older_statusline_and_say_where_they_came_from(pg_db) -> None:
    from app.services.subscription_accounting import collector
    from app.services.subscription_accounting.summary import _utilization

    t0 = datetime(2026, 10, 28, 12, tzinfo=UTC)
    reset = t0 + timedelta(hours=3)
    stale = collector.SnapshotEvent(
        "claude", t0, 300, 8.0, reset, None, None, collector.SOURCE_CLAUDE_STATUSLINE
    )
    week = collector.SnapshotEvent(
        "claude", t0, 10080, 50.0, t0 + timedelta(days=2), None, None, collector.SOURCE_CLAUDE_STATUSLINE
    )
    newer = (t0 + timedelta(minutes=40)).timestamp()
    pg_db.add_all(
        [
            window_attempt("claude", newer, {"five_hour": 0.31, "seven_day": 0.52}, rate_limit_observed_at=newer),
            window_attempt("codex", newer, {"five_hour": 0.4, "seven_day": 0.06}, rate_limit_resets={"five_hour": 1793035965}),
            window_attempt("pi", newer, {"five_hour": 0.9}),  # not a subscription window source
            window_attempt("claude", newer, {"hour": 0.1}),  # a window the page does not know
        ]
    )
    await pg_db.flush()
    state: dict = {}
    events = await collector.workflow_snapshot_events(pg_db, state, t0 + timedelta(hours=1))
    assert sorted((e.provider, e.window_minutes, e.used_percent, e.source) for e in events) == [
        ("claude", 300, 31.0, "workflow_attempt"),
        ("claude", 10080, 52.0, "workflow_attempt"),
        ("codex", 300, 40.0, "workflow_attempt"),
        ("codex", 10080, 6.0, "workflow_attempt"),
    ]
    assert state["since"] == newer
    # A second pass over the same attempts reads them again but the selection keeps each reading once.
    kept = collector.select_snapshots([stale, week, *events], {})
    assert [(e.provider, e.window_minutes, e.source) for e in kept if e.provider == "claude"] == [
        ("claude", 300, "claude_statusline"),
        ("claude", 10080, "claude_statusline"),
        ("claude", 300, "workflow_attempt"),
        ("claude", 10080, "workflow_attempt"),
    ]
    # The attempt did not say when the window resets: it keeps the reset of the window already on record.
    assert {e.resets_at for e in kept if e.source == "workflow_attempt" and e.provider == "claude"} == {
        reset,
        t0 + timedelta(days=2),
    }
    for e in kept:
        pg_db.add(
            SubscriptionUsageSnapshot(
                provider=e.provider, observed_at=e.ts, window_minutes=e.window_minutes,
                used_percent=e.used_percent, resets_at=e.resets_at, source=e.source,
            )
        )
    await pg_db.flush()
    page = {p["provider"]: p for p in await _utilization(pg_db, t0 + timedelta(hours=1))}
    five = next(w for w in page["claude"]["windows"] if w["window_minutes"] == 300)
    assert (five["used_percent"], five["source"], five["source_label"]) == (31.0, "workflow_attempt", "workflow run")
    assert five["observed_at"] == (t0 + timedelta(minutes=40)).isoformat()
    # A statusline reading newer than the workflow attempt wins instead.
    pg_db.add(
        SubscriptionUsageSnapshot(
            provider="claude", observed_at=t0 + timedelta(minutes=50), window_minutes=300, used_percent=33.0,
            resets_at=reset, source="claude_statusline",
        )
    )
    await pg_db.flush()
    page = {p["provider"]: p for p in await _utilization(pg_db, t0 + timedelta(hours=1))}
    five = next(w for w in page["claude"]["windows"] if w["window_minutes"] == 300)
    assert (five["used_percent"], five["source"]) == (33.0, "claude_statusline")


# --- cancel, orphans and the served model -----------------------------------------------------------------

# A harness stand-in: a leader and a grandchild in one process group, both sleeping, the pids reported on stdout.
TREE = (
    "import json, subprocess, sys, time\n"
    "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(300)'])\n"
    "print(json.dumps({'child': child.pid}), flush=True)\n"
    "time.sleep(300)\n"
)
FAST = {"heartbeat_interval_seconds": 0.2, "process_stop_grace_seconds": 3}


def running(pid: int) -> bool:
    stat = read_stat(pid)
    return stat is not None and stat.state != "Z"


async def gone(*pids: int, within: float = 10.0) -> bool:
    deadline = asyncio.get_running_loop().time() + within
    while any(running(pid) for pid in pids):
        if asyncio.get_running_loop().time() > deadline:
            return False
        await asyncio.sleep(0.05)
    return True


class TreeExecutor:
    """Runs a real process tree through the executors' own HarnessProcess for the steps named, the faux for the rest."""

    def __init__(self, faux: FauxExecutor, steps: set[str]) -> None:
        self.faux, self.steps = faux, steps
        self.leader: int | None = None
        self.child: int | None = None
        self.started = asyncio.Event()

    async def run(self, packet, model, worktree, run_dir, on_event) -> StepResult:
        if packet.step_key not in self.steps:
            return await self.faux.run(packet, model, worktree, run_dir, on_event)
        defaults = load_defaults()
        harness = await HarnessProcess.start(
            [sys.executable, "-c", TREE], worktree, child_env(defaults), 1000, stdin=False
        )
        self.leader = harness.process.pid
        try:
            async for record in harness.records():
                self.child = record["child"]
                self.started.set()
        finally:
            await harness.stop(defaults["terminate_grace_seconds"])
        return StepResult("failed", error="the harness ended")


def with_tree(world: World, *steps: str) -> TreeExecutor:
    tree = TreeExecutor(world.faux, set(steps))
    world.deps.get_executor = lambda _kind: tree
    return tree


class LiveTreeExecutor(TreeExecutor):
    """A real harness process that reports a phase, then finishes like the faux once released."""

    def __init__(self, faux: FauxExecutor, steps: set[str]) -> None:
        super().__init__(faux, steps)
        self.release = asyncio.Event()

    async def run(self, packet, model, worktree, run_dir, on_event) -> StepResult:
        if packet.step_key not in self.steps:
            return await self.faux.run(packet, model, worktree, run_dir, on_event)
        defaults = load_defaults()
        harness = await HarnessProcess.start(
            [sys.executable, "-c", TREE], worktree, child_env(defaults), 1000, stdin=False
        )
        self.leader = harness.process.pid
        try:
            async for record in harness.records():
                self.child = record["child"]
                note_live("tool:Bash")
                self.started.set()
                await self.release.wait()
                break
        finally:
            await harness.stop(defaults["terminate_grace_seconds"])
        return await self.faux.run(packet, model, worktree, run_dir, on_event)


async def test_a_running_step_shows_its_phase_last_activity_and_live_harness_process(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    tree = LiveTreeExecutor(world.faux, {"plan"})
    world.deps.get_executor = lambda _kind: tree
    run_id, _ = await create_run(
        pg_db, example("plan-implement-review-fix", repo, policy=FAST), deps=world.deps
    )
    advancing = asyncio.create_task(world.run_to_stop(run_id))
    await asyncio.wait_for(tree.started.wait(), 20)
    live: dict[str, Any] | None = None
    for _ in range(100):  # the heartbeat saves it at its own rate (0.2s here), never per event
        async with world.lock:
            live = (await view_of(pg_db, run_id))["steps"][0]["live"]
        if live and live["harness_pid"]:
            break
        await asyncio.sleep(0.1)
    assert live is not None
    assert (live["phase"], live["harness_pid"], live["harness_alive"]) == ("tool:Bash", tree.leader, True)
    assert live["last_event_at"] and live["updated_at"]
    tree.release.set()
    assert (await asyncio.wait_for(advancing, 30))["reason"] == "completed"
    view = await view_of(pg_db, run_id)
    assert all(step["live"] is None for step in view["steps"])  # shown only while the step runs


async def test_cancelling_a_running_step_stops_its_process_tree_and_the_run_goes_on(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    tree = with_tree(world, "plan")
    run_id, _ = await create_run(
        pg_db, example("plan-implement-review-fix", repo, policy=FAST), deps=world.deps
    )
    advancing = asyncio.create_task(world.run_to_stop(run_id))
    await asyncio.wait_for(tree.started.wait(), 20)
    assert running(tree.leader) and running(tree.child)

    async with world.lock:
        asked = await cancel_step(
            pg_db, run_id, "plan", CancelRequest(reason="wrong approach"), requested_by="summitflow", deps=world.deps
        )
        again = await cancel_step(pg_db, run_id, "plan", CancelRequest(), requested_by="other", deps=world.deps)
    assert asked["cancelling"] and again["cancel"] == asked["cancel"]  # the second ask changes nothing
    assert (asked["cancel"]["scope"], asked["cancel"]["requested_by"], asked["cancel"]["reason"]) == (
        "step",
        "summitflow",
        "wrong approach",
    )

    assert (await asyncio.wait_for(advancing, 30))["reason"] == "completed"
    assert await gone(tree.leader, tree.child, within=5)  # within the grace period (3s), not the 300s of the sleeps
    view = await view_of(pg_db, run_id)
    plan, *rest = view["steps"]
    (attempt,) = plan["attempt_history"]
    assert plan["status"] == "cancelled" and plan["cancel"]["reason"] == "wrong approach"
    assert attempt["outcome"] == {"kind": "cancelled", "requested_model": OPUS, "explanation": "wrong approach"}
    assert attempt["decision"] == {"action": "cancelled", "reason": "cancelled"} and attempt["status"] == "failed"
    assert plan["attempts"] == 1 and [c["model"] for c in world.faux.calls if c["step"] == "plan"] == []
    # No next model for the cancelled step, and the other steps ran.
    assert [s["status"] for s in rest] == ["completed"] * len(rest) and view["state"] == "completed"
    assert [p["kind"] for p in attempt["processes"]] == ["harness"] and attempt["processes"][0]["pid"] == tree.leader


async def test_cancelling_the_run_stops_the_step_and_skips_what_has_not_started(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    tree = with_tree(world, "plan")
    run_id, _ = await create_run(
        pg_db, example("plan-implement-review-fix", repo, policy=FAST), deps=world.deps
    )
    advancing = asyncio.create_task(world.run_to_stop(run_id))
    await asyncio.wait_for(tree.started.wait(), 20)
    async with world.lock:
        asked = await cancel_run(pg_db, run_id, CancelRequest(reason="not needed"), requested_by="owner", deps=world.deps)
        again = await cancel_run(pg_db, run_id, CancelRequest(), deps=world.deps)
    assert asked["state"] == "running" and asked["cancelling"] and again["cancel"] == asked["cancel"]

    result = await asyncio.wait_for(advancing, 30)
    assert (result["run_state"], result["reason"]) == ("cancelled", "cancelled")
    assert await gone(tree.leader, tree.child, within=5)
    view = await view_of(pg_db, run_id)
    assert view["state"] == "cancelled" and view["cancel"]["reason"] == "not needed" and not view["cancelling"]
    assert [s["status"] for s in view["steps"]] == ["cancelled", "skipped", "skipped", "skipped"]
    assert view["steps"][1]["outcome"] is None and view["steps"][0]["attempt_history"][0]["outcome"]["kind"] == "cancelled"
    skipped = (await pg_db.execute(select(WorkflowStep).where(WorkflowStep.step_key == view["steps"][1]["key"]))).scalar_one()
    assert skipped.outcome["skipped"] == "run_cancelled"
    assert world.faux.calls == []
    run = (await pg_db.execute(select(Session).where(Session.id == run_id))).scalar_one()
    assert (run.status, run.health_detail) == ("failed", "cancelled")
    # Nothing is left to advance or cancel.
    assert (await advance_run(run_id, deps=world.deps))["reason"] == "run_cancelled"
    with pytest.raises(WorkflowRunError) as finished:
        await cancel_run(pg_db, run_id, CancelRequest(), deps=world.deps)
    assert finished.value.code == "already_finished" and finished.value.extra == {"state": "cancelled"}


async def test_cancelling_a_run_with_nothing_running_ends_it_at_once(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    result = await cancel_run(pg_db, run_id, CancelRequest(reason="changed my mind"), deps=world.deps)
    assert (result["state"], result["cancelling"]) == ("cancelled", False)
    view = await view_of(pg_db, run_id)
    assert {s["status"] for s in view["steps"]} == {"skipped"} and view["cancel"]["requested_at"] == NOW


async def test_cancelling_a_waiting_step_skips_it_for_good_and_the_run_continues(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("refuse", category="cyber")]})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "chain_exhausted"
    result = await cancel_step(pg_db, run_id, "plan", CancelRequest(), deps=world.deps)
    assert (result["state"], result["status"], result["cancelling"]) == ("running", "cancelled", False)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert (await view_of(pg_db, run_id))["steps"][0]["status"] == "cancelled"


async def test_recovery_stops_a_recorded_live_group_and_spares_a_reused_pid(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(
        pg_db,
        example("plan-implement-review-fix", repo, policy={"stale_after_seconds": 100, "process_stop_grace_seconds": 3}),
        deps=world.deps,
    )
    _early, intent = await engine_module._commit_intent(run_id, world.deps)
    assert intent is not None
    # The orphaned harness: its worker is gone, but the group (with its marker) runs on and is recorded.
    orphan = subprocess.Popen(
        [sys.executable, "-c", TREE],
        start_new_session=True,
        stdout=subprocess.PIPE,
        text=True,
        env={**os.environ, MARKER_ENV: intent.attempt_id},
    )
    assert orphan.stdout is not None
    child = json.loads(orphan.stdout.readline())["child"]
    # Another process whose pid the record names with a different start time: the pid was reused.
    bystander = subprocess.Popen(["sleep", "300"], start_new_session=True)
    try:
        for who, shift in ((orphan.pid, 0), (bystander.pid, 1)):
            identity = identify(who)
            assert identity is not None
            await engine_module._record_process(
                world.deps,
                intent.attempt_id,
                {"kind": "harness", **{**identity.as_dict(), "start_time": identity.start_time + shift}},
            )
        await RunWorkspace.from_meta(intent.meta).ensure()
        junk = Path((await view_of(pg_db, run_id))["worktree"]) / "half-written.txt"
        junk.write_text("partial")

        world.clock += 500
        assert await recover_stale_steps(world.deps) == [run_id]
        assert orphan.wait(timeout=10) != 0 and await gone(child, within=5)  # stopped before anything was reset
        assert running(bystander.pid)  # never signalled
        view = await view_of(pg_db, run_id)
        (attempt,) = view["steps"][0]["attempt_history"]
        assert [p["recovery"] for p in attempt["processes"]] == ["terminated", "pid_reused"]
        assert "stopped the old process group" in attempt["error"] and view["steps"][0]["status"] == "pending"
        await advance_run(run_id, deps=world.deps)
        assert not junk.exists()  # the reset ran after the old group was stopped
    finally:
        bystander.kill()
        bystander.wait()
        if orphan.poll() is None:
            orphan.kill()


async def test_a_stale_step_that_was_cancelled_ends_cancelled_instead_of_restarting(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(
        pg_db, example("plan-implement-review-fix", repo, policy={"stale_after_seconds": 100}), deps=world.deps
    )
    await engine_module._commit_intent(run_id, world.deps)  # the worker dies mid-step
    await cancel_run(pg_db, run_id, CancelRequest(reason="stop"), deps=world.deps)
    world.clock += 500
    assert await recover_stale_steps(world.deps) == []
    view = await view_of(pg_db, run_id)
    assert view["state"] == "cancelled" and view["steps"][0]["status"] == "cancelled"
    assert view["steps"][0]["restarts"] == 0
    assert view["steps"][0]["attempt_history"][0]["outcome"]["kind"] == "cancelled"


async def test_cancel_endpoints_record_who_asked_and_answer_409_for_finished_targets(
    pg_db, repo, world_factory, monkeypatch
) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api import workflow_runs as api
    from app.db import get_db

    queued: list[str] = []

    async def enqueue(run_id: str) -> None:
        queued.append(run_id)

    monkeypatch.setattr(api, "_enqueue", enqueue)
    monkeypatch.setattr(engine_module, "EngineDeps", lambda: world.deps)
    world = world_factory({})
    chains(world)
    second, _ = await create_run(pg_db, example("plan-implement-review-fix", repo, request_id="second"), deps=world.deps)
    assert (await world.run_to_stop(second))["reason"] == "completed"
    app = FastAPI()
    app.include_router(api.router)

    async def override() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = override
    headers = {"X-Client-Id": "summitflow", "X-Request-Source": "proof"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # A finished run and a finished step answer 409 with where things stand.
        done = await client.post(f"/workflow-runs/{second}/cancel", headers=headers)
        assert done.status_code == 409 and done.json()["detail"] == {
            "code": "already_finished",
            "error": "already_finished",
            "message": "run is already completed",
            "details": {"state": "completed"},
            "state": "completed",
        }
        step = await client.post(f"/workflow-runs/{second}/steps/plan/cancel")
        assert step.status_code == 409 and step.json()["detail"]["state"] == "completed"
        assert (await client.post("/workflow-runs/missing/cancel")).status_code == 404

        fresh, _ = await create_run(pg_db, example("plan-implement-review-fix", repo, request_id="third"), deps=world.deps)
        missing = await client.post(f"/workflow-runs/{fresh}/steps/nope/cancel")
        assert missing.status_code == 404 and missing.json()["detail"]["code"] == "step_not_found"
        cancelled = await client.post(f"/workflow-runs/{fresh}/cancel", json={"reason": "enough"}, headers=headers)
        body = cancelled.json()
        assert cancelled.status_code == 200 and body["state"] == "cancelled"
        assert (body["cancel"]["requested_by"], body["cancel"]["request_source"], body["cancel"]["reason"]) == (
            "summitflow",
            "proof",
            "enough",
        )
        assert (await client.post(f"/workflow-runs/{fresh}/cancel")).status_code == 409
        assert (await client.get(f"/workflow-runs/{fresh}")).json()["cancel"]["requested_by"] == "summitflow"

        # Cancelling a step that has not started: the run goes on, so an advance is queued.
        live, _ = await create_run(pg_db, example("plan-implement-review-fix", repo, request_id="fourth"), deps=world.deps)
        ok = await client.post(f"/workflow-runs/{live}/steps/plan/cancel", json={})
        assert ok.status_code == 200 and ok.json()["status"] == "cancelled" and queued == [live]


async def test_the_view_shows_the_model_that_answered_when_it_is_the_one_requested(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    await world.run_to_stop(run_id)
    row = (await pg_db.execute(select(Session).where(Session.parent_session_id == run_id).limit(1))).scalar_one()
    assert "served_model" not in (row.provider_metadata or {})  # stored only when it differs from the request
    (attempt,) = (await view_of(pg_db, run_id))["steps"][0]["attempt_history"]
    assert attempt["served_model"] == OPUS == attempt["served_models"][-1]


async def test_an_equal_workflow_window_reading_refreshes_source_and_time() -> None:
    from app.services.subscription_accounting import collector

    t0 = datetime(2026, 10, 28, 12, tzinfo=UTC)
    reset = t0 + timedelta(hours=3)
    old = collector.SnapshotEvent("claude", t0, 300, 31.0, reset, None, None, None)  # recorded before sources existed
    same = collector.SnapshotEvent("claude", t0 + timedelta(minutes=2), 300, 31.0, reset, None, None, collector.SOURCE_WORKFLOW)
    lower = collector.SnapshotEvent("claude", t0 + timedelta(minutes=3), 300, 20.0, reset, None, None, collector.SOURCE_WORKFLOW)
    again = collector.SnapshotEvent("claude", t0 + timedelta(minutes=2), 300, 31.0, reset, None, None, collector.SOURCE_WORKFLOW)
    state: dict = {}
    kept = collector.select_snapshots([old], state)
    kept += collector.select_snapshots([same, lower, again], state)
    # The equal reading is kept with its own source and time; a lower one and a re-read of the same one are not.
    assert [(e.source, e.ts, e.used_percent) for e in kept] == [
        (None, t0, 31.0),
        (collector.SOURCE_WORKFLOW, t0 + timedelta(minutes=2), 31.0),
    ]


# --- the plan as a dependency graph, and revising it while the run goes -----------------------------


def graph(repo: Path, *steps: dict[str, Any], **extra: Any) -> RunDefinition:
    """A run of faux steps: each dict is a step (key, optional depends_on / agent_slug ...)."""

    policy = {"heartbeat_interval_seconds": 3600, **extra.pop("policy", {})}
    return RunDefinition(
        goal="graph",
        project_id="p",
        repo_path=str(repo),
        policy=policy,
        steps=[
            {"instructions": f"do {s['key']}", "agent_slug": "coder", "executor": "faux", **s}
            for s in steps
        ],
        **extra,
    )


def order(world: World) -> list[str]:
    return [c["step"] for c in world.faux.calls]


def context_of(world: World, key: str) -> str:
    """The earlier-steps part of the packet the step got: only handoffs the step was given."""

    packet = next(c["packet"] for c in world.faux.calls if c["step"] == key)
    return packet.split("# Earlier steps", 1)[1] if "# Earlier steps" in packet else ""


class Gate:
    """An executor that holds one step open until released, so the test can act while it runs."""

    def __init__(self, faux: FauxExecutor, step: str) -> None:
        self.faux, self.step = faux, step
        self.started, self.release = asyncio.Event(), asyncio.Event()

    async def run(self, packet, model, worktree, run_dir, on_event) -> StepResult:
        if packet.step_key == self.step:
            self.started.set()
            await self.release.wait()
        return await self.faux.run(packet, model, worktree, run_dir, on_event)


async def test_default_chain_depends_on_the_previous_step_and_keeps_its_context(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, example("plan-implement-review-fix", repo), deps=world.deps)
    view = await view_of(pg_db, run_id)
    assert [s["depends_on"] for s in view["steps"]] == [[], ["plan"], ["implement"], ["review"]]
    assert [s["readiness"]["state"] for s in view["steps"]] == ["ready", "waiting", "waiting", "waiting"]
    assert view["steps"][2]["readiness"]["reason"] == "waiting for implement"
    assert (view["plan_revision"], view["plan_history"]) == (0, [])
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert order(world) == ["plan", "implement", "review", "fix"]
    ctx = context_of(world, "fix")
    assert [ctx.index(f"## {k} (") for k in ("plan", "implement", "review")] == sorted(
        ctx.index(f"## {k} (") for k in ("plan", "implement", "review")
    ) and ctx.count("## ") == 3


async def test_diamond_runs_in_topological_order_with_context_from_dependencies_only(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    definition = graph(
        repo,
        {"key": "d", "depends_on": ["b", "c"]},  # declared first: position does not decide the order
        {"key": "b", "depends_on": ["a"]},
        {"key": "c", "depends_on": ["a"]},
        {"key": "a", "depends_on": []},
        {"key": "side", "depends_on": []},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    view = await view_of(pg_db, run_id)
    assert {s["key"]: s["readiness"]["state"] for s in view["steps"]} == {
        "d": "waiting",
        "b": "waiting",
        "c": "waiting",
        "a": "ready",
        "side": "ready",
    }
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    # One at a time, the first ready step by position each time: a and side are ready, a is first; then b, c, d.
    assert order(world) == ["a", "b", "c", "d", "side"]
    ctx_d = context_of(world, "d")
    assert all(f"## {k} (" in ctx_d for k in ("a", "b", "c")) and "## side (" not in ctx_d
    assert context_of(world, "b").count("## ") == 1 and "## a (" in context_of(world, "b")
    assert context_of(world, "side") == "" and context_of(world, "a") == ""


async def test_a_cycle_or_unknown_dependency_is_rejected(pg_db, repo, world_factory) -> None:
    with pytest.raises(ValueError, match="cycle"):
        graph(repo, {"key": "a", "depends_on": ["b"]}, {"key": "b", "depends_on": ["a"]})
    with pytest.raises(ValueError, match="unknown step"):
        graph(repo, {"key": "a"}, {"key": "b", "depends_on": ["nope"]})
    with pytest.raises(ValueError, match="cycle"):
        graph(repo, {"key": "a", "depends_on": ["a"]})
    # An explicit dependency on a later step makes the default chain after it circular.
    with pytest.raises(ValueError, match="cycle"):
        graph(repo, {"key": "a", "depends_on": ["b"]}, {"key": "b"})

    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}), deps=world.deps)
    with pytest.raises(WorkflowRunError) as unknown:
        await add_steps(pg_db, run_id, AddSteps(steps=[{"key": "c", "instructions": "x", "agent_slug": "coder", "depends_on": ["zz"]}]), deps=world.deps)
    assert unknown.value.code == "invalid_plan"
    with pytest.raises(WorkflowRunError) as cycle:
        await revise_step(pg_db, run_id, "a", StepRevision(depends_on=["b"]), deps=world.deps)
    assert cycle.value.code == "invalid_plan" and "cycle" in str(cycle.value)
    assert (await view_of(pg_db, run_id))["plan_revision"] == 0


async def test_a_step_added_mid_run_runs_with_its_dependencies_context(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "one"}, {"key": "two"}), deps=world.deps)
    assert (await advance_run(run_id, deps=world.deps))["next"] == "continue"  # step one done
    added = await add_steps(
        pg_db,
        run_id,
        AddSteps(
            steps=[{"key": "extra", "instructions": "more", "agent_slug": "coder", "executor": "faux"}],
            after="one",
            changed_by="aico-1",
            reason="found more work",
        ),
        requested_by="summitflow",
        request_source="test",
        deps=world.deps,
    )
    assert (added["plan_revision"], added["added"], added["reopened"], added["enqueue"]) == (1, ["extra"], False, True)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert order(world) == ["one", "two", "extra"]  # first ready by position; extra depends only on one
    assert "## one (" in context_of(world, "extra") and "## two (" not in context_of(world, "extra")
    view = await view_of(pg_db, run_id)
    (entry,) = view["plan_history"]
    assert view["plan_revision"] == 1 and entry["action"] == "add_steps" and entry["reason"] == "found more work"
    assert entry["by"] == {"changed_by": "aico-1", "client_id": "summitflow", "request_source": "test"}
    assert entry["at"] == NOW and entry["changes"][0]["step"] == "extra" and entry["changes"][0]["before"] is None
    assert entry["changes"][0]["after"]["depends_on"] == ["one"]
    with pytest.raises(WorkflowRunError) as clash:
        await add_steps(pg_db, run_id, AddSteps(steps=[{"key": "one", "instructions": "x", "agent_slug": "coder"}]), deps=world.deps)
    assert clash.value.code == "duplicate_step"


async def test_revising_a_pending_step_changes_its_model_and_clears_the_cached_chain(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"b": [FauxAction("refuse", category="cyber"), FauxAction("success")]})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}), deps=world.deps)
    await advance_run(run_id, deps=world.deps)  # a
    await advance_run(run_id, deps=world.deps)  # b refused on OPUS: pending again, chain cached, OPUS tried
    row = (await pg_db.execute(select(WorkflowStep).where(WorkflowStep.step_key == "b"))).scalar_one()
    assert row.status == "pending" and row.outcome["chain"] == [OPUS, CODEX, OPUS_OLD] and row.outcome["tried"] == [OPUS]

    result = await revise_step(
        pg_db, run_id, "b", StepRevision(model_override=OPUS_OLD, instructions="do b differently", effort="high"), deps=world.deps
    )
    assert (result["changed"], result["plan_revision"], result["enqueue"]) == (True, 1, True)
    await pg_db.refresh(row)
    assert "chain" not in row.outcome and row.outcome["tried"] == [] and row.definition["model_override"] == OPUS_OLD
    same = await revise_step(pg_db, run_id, "b", StepRevision(effort="high"), deps=world.deps)
    assert same["changed"] is False and same["plan_revision"] == 1  # nothing differs: no new revision
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert [c["model"] for c in world.faux.calls if c["step"] == "b"] == [OPUS, OPUS_OLD]
    assert "do b differently" in next(c["packet"] for c in reversed(world.faux.calls) if c["step"] == "b")
    view = await view_of(pg_db, run_id)
    (entry,) = view["plan_history"]
    (change,) = entry["changes"]
    assert entry["action"] == "revise_step" and change["before"]["model_override"] is None
    assert change["after"] == {"model_override": OPUS_OLD, "instructions": "do b differently", "effort": "high"}


async def test_revising_a_step_that_has_started_is_refused_with_its_state(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    gate = Gate(world.faux, "a")
    world.deps.get_executor = lambda _kind: gate
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}), deps=world.deps)
    advancing = asyncio.create_task(world.run_to_stop(run_id))
    await asyncio.wait_for(gate.started.wait(), 20)
    async with world.lock:
        with pytest.raises(WorkflowRunError) as running:
            await revise_step(pg_db, run_id, "a", StepRevision(effort="low"), deps=world.deps)
        assert (running.value.code, running.value.extra["step_status"], running.value.extra["state"]) == (
            "step_not_pending",
            "running",
            "running",
        )
        with pytest.raises(WorkflowRunError) as removal:
            await remove_step(pg_db, run_id, "a", deps=world.deps)
        assert removal.value.code == "step_not_pending"
        # A pending step can be revised while another runs, and the run takes no extra advance for it.
        ok = await revise_step(pg_db, run_id, "b", StepRevision(effort="low"), deps=world.deps)
        assert ok["changed"] and ok["enqueue"] is False
    gate.release.set()
    assert (await asyncio.wait_for(advancing, 30))["reason"] == "completed"
    with pytest.raises(WorkflowRunError) as done:
        await revise_step(pg_db, run_id, "a", StepRevision(effort="low"), deps=world.deps)
    assert done.value.code == "already_finished"  # the run is complete
    view = await view_of(pg_db, run_id)
    assert view["plan_revision"] == 1


async def test_removing_a_step_others_depend_on_is_refused_unless_they_are_revised_in_the_call(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    definition = graph(repo, {"key": "a"}, {"key": "b", "depends_on": ["a"]}, {"key": "c", "depends_on": ["b"]})
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    with pytest.raises(WorkflowRunError) as refused:
        await remove_step(pg_db, run_id, "b", deps=world.deps)
    assert refused.value.code == "has_dependents" and refused.value.extra["dependents"] == ["c"]
    with pytest.raises(WorkflowRunError) as dangling:
        await remove_step(pg_db, run_id, "b", RemoveStep(revise={"c": StepRevision(depends_on=["b"])}), deps=world.deps)
    assert dangling.value.code == "invalid_plan"
    assert [s["key"] for s in (await view_of(pg_db, run_id))["steps"]] == ["a", "b", "c"]

    done = await remove_step(
        pg_db, run_id, "b", RemoveStep(revise={"c": StepRevision(depends_on=["a"])}, changed_by="aico-1"), deps=world.deps
    )
    assert (done["removed"], done["plan_revision"]) == ("b", 1)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert order(world) == ["a", "c"]
    view = await view_of(pg_db, run_id)
    (entry,) = view["plan_history"]
    assert [(c["step"], c["op"]) for c in entry["changes"]] == [("b", "remove"), ("c", "revise")]
    assert entry["changes"][0]["before"]["key"] == "b" and entry["changes"][1]["after"] == {"depends_on": ["a"]}


async def test_removing_a_step_on_the_default_chain_relinks_the_next_one(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}, {"key": "c"}), deps=world.deps)
    result = await remove_step(pg_db, run_id, "b", deps=world.deps)
    assert result["relinked"] == ["c"]
    view = await view_of(pg_db, run_id)
    assert [(s["key"], s["depends_on"]) for s in view["steps"]] == [("a", []), ("c", ["a"])]


async def test_adding_to_a_completed_run_reopens_it_and_a_failed_or_cancelled_run_refuses(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}), deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    run = await pg_db.get(Session, run_id)
    assert run.status == "completed" and (await view_of(pg_db, run_id))["state"] == "completed"

    result = await add_steps(
        pg_db, run_id, AddSteps(steps=[{"key": "more", "instructions": "again", "agent_slug": "coder", "executor": "faux"}]), deps=world.deps
    )
    assert (result["state"], result["reopened"], result["enqueue"]) == ("running", True, True)
    await pg_db.refresh(run)
    assert run.status == "active" and (await view_of(pg_db, run_id))["state"] == "running"
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert order(world) == ["a", "more"] and "## a (" in context_of(world, "more")
    assert (await view_of(pg_db, run_id))["state"] == "completed"

    cancelled, _ = await create_run(pg_db, graph(repo, {"key": "a"}, request_id="c1"), deps=world.deps)
    await cancel_run(pg_db, cancelled, CancelRequest(), deps=world.deps)
    with pytest.raises(WorkflowRunError) as refused:
        await add_steps(pg_db, cancelled, AddSteps(steps=[{"key": "z", "instructions": "x", "agent_slug": "coder"}]), deps=world.deps)
    assert (refused.value.code, refused.value.extra["state"]) == ("already_finished", "cancelled")

    failing = world_factory({"a": [FauxAction("refuse", category="cyber")]})
    chains(failing)
    failed, _ = await create_run(pg_db, graph(repo, {"key": "a"}, request_id="f1"), deps=failing.deps)
    assert (await failing.run_to_stop(failed))["reason"] == "chain_exhausted"
    await resume_run(pg_db, failed, OwnerDecision(action="fail"), deps=failing.deps)
    with pytest.raises(WorkflowRunError) as refused_failed:
        await revise_step(pg_db, failed, "a", StepRevision(effort="low"), deps=failing.deps)
    assert refused_failed.value.extra["state"] == "failed"


async def test_a_dependency_that_will_never_complete_blocks_its_dependents_and_a_revision_unblocks_them(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"a": [FauxAction("refuse", category="cyber")]})
    chains(world)
    definition = graph(repo, {"key": "a"}, {"key": "b", "depends_on": ["a"]}, {"key": "c", "depends_on": []})
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "chain_exhausted"
    await resume_run(pg_db, run_id, OwnerDecision(action="skip"), deps=world.deps)
    result = await world.run_to_stop(run_id)
    assert (result["reason"], order(world)[-1]) == ("blocked_dependencies", "c")
    view = await view_of(pg_db, run_id)
    b = view["steps"][1]
    assert (view["state"], view["pause"]["reason"], view["pause"]["step_key"]) == ("needs_owner", "blocked_dependencies", "b")
    assert b["readiness"]["state"] == "blocked" and b["readiness"]["reason"] == "blocked by a (skipped)"
    with pytest.raises(WorkflowRunError, match="blocked on dependencies") as not_a_step_decision:
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
    assert not_a_step_decision.value.code == "blocked_dependencies"
    with pytest.raises(WorkflowRunError, match="skipped"):  # no new dependency on a dead step
        await revise_step(pg_db, run_id, "b", StepRevision(depends_on=["a", "c"]), deps=world.deps)

    fixed = await revise_step(pg_db, run_id, "b", StepRevision(depends_on=["c"]), deps=world.deps)
    assert (fixed["state"], fixed["enqueue"]) == ("running", True)
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert order(world)[-1] == "b"


async def test_a_default_dependency_looks_through_a_skipped_step(pg_db, repo, world_factory) -> None:
    world = world_factory({"b": [FauxAction("refuse", category="cyber")]})
    chains(world)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}, {"key": "c"}), deps=world.deps)
    assert (await world.run_to_stop(run_id))["reason"] == "chain_exhausted"
    await resume_run(pg_db, run_id, OwnerDecision(action="skip"), deps=world.deps)
    view = await view_of(pg_db, run_id)
    assert view["steps"][2]["depends_on"] == ["a"] and view["steps"][2]["readiness"]["state"] == "ready"
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    assert "## a (" in context_of(world, "c") and "## b (" not in context_of(world, "c")


async def test_request_id_with_a_different_definition_is_refused_and_the_same_one_returns_the_run(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({})
    chains(world)
    first, created = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}, request_id="r1"), deps=world.deps)
    same, again = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}, request_id="r1"), deps=world.deps)
    assert (created, again, same) == (True, False, first)
    for changed in (
        graph(repo, {"key": "a"}, {"key": "b", "instructions": "something else"}, request_id="r1"),  # later step
        graph(repo, {"key": "a"}, {"key": "b", "depends_on": []}, request_id="r1"),
        graph(repo, {"key": "x"}, request_id="r1"),  # different first step
    ):
        with pytest.raises(WorkflowRunError) as conflict:
            await create_run(pg_db, changed, deps=world.deps)
        assert conflict.value.code == "request_id_conflict" and conflict.value.extra["run_id"] == first
    # Revising the run afterwards does not make the original request a different one.
    await revise_step(pg_db, first, "b", StepRevision(effort="low"), deps=world.deps)
    assert (await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}, request_id="r1"), deps=world.deps))[1] is False
    assert await pg_db.scalar(select(WorkflowStep.id).where(WorkflowStep.step_key == "x")) is None


async def test_the_run_records_who_launched_it(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    run_id, _ = await create_run(
        pg_db, graph(repo, {"key": "a"}, launched_by="aico-session-7", coordinator="claude-code"), deps=world.deps
    )
    view = await view_of(pg_db, run_id)
    assert (view["launched_by"], view["coordinator"]) == ("aico-session-7", "claude-code")
    from app.services.workflow_runs.listing import list_runs

    (item,) = (await list_runs(pg_db))["runs"]
    assert (item["launched_by"], item["coordinator"], item["plan_revision"]) == ("aico-session-7", "claude-code", 0)
    plain, _ = await create_run(pg_db, graph(repo, {"key": "a"}, request_id="p"), deps=world.deps)
    assert (await view_of(pg_db, plain))["launched_by"] is None


async def test_plan_revision_endpoints_answer_409_for_a_started_step_and_queue_an_advance(
    pg_db, repo, world_factory, monkeypatch
) -> None:
    from fastapi import FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api import workflow_runs as api
    from app.db import get_db
    from app.services.workflow_runs import revisions as revisions_module

    queued: list[str] = []

    async def enqueue(run_id: str) -> None:
        queued.append(run_id)

    world = world_factory({})
    chains(world)
    monkeypatch.setattr(api, "_enqueue", enqueue)
    monkeypatch.setattr(revisions_module, "EngineDeps", lambda: world.deps)
    run_id, _ = await create_run(pg_db, graph(repo, {"key": "a"}, {"key": "b"}), deps=world.deps)
    await advance_run(run_id, deps=world.deps)  # a completed; b pending
    app = FastAPI()
    app.include_router(api.router)

    async def override() -> AsyncGenerator[AsyncSession]:
        yield pg_db

    app.dependency_overrides[get_db] = override
    headers = {"X-Client-Id": "summitflow", "X-Request-Source": "proof"}
    base = f"/workflow-runs/{run_id}/steps"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        added = await client.post(
            base,
            json={"steps": [{"key": "c", "instructions": "x", "agent_slug": "coder", "executor": "faux"}], "after": "a", "changed_by": "aico-9"},
            headers=headers,
        )
        body = added.json()
        assert added.status_code == 200 and body["added"] == ["c"] and body["plan_revision"] == 1
        assert queued == [run_id] and body["run"]["plan_history"][0]["by"]["client_id"] == "summitflow"
        assert [s["depends_on"] for s in body["run"]["steps"]] == [[], ["a"], ["a"]]

        patched = await client.patch(f"{base}/b", json={"effort": "high", "reason": "harder than it looked"})
        assert patched.status_code == 200 and patched.json()["run"]["steps"][1]["effort"] == "high"
        assert (await client.patch(f"{base}/a", json={"effort": "low"})).status_code == 409  # completed
        refused = await client.patch(f"{base}/a", json={"effort": "low"})
        assert refused.json()["detail"]["code"] == "step_not_pending" and refused.json()["detail"]["step_status"] == "completed"
        assert (await client.patch(f"{base}/b", json={"depends_on": ["c", "b"]})).status_code == 422
        assert (await client.patch(f"{base}/b", json={"bogus": 1})).status_code == 422
        assert (await client.patch(f"{base}/nope", json={"effort": "low"})).status_code == 404
        assert (await client.post(base, json={"steps": [{"key": "c", "instructions": "x", "agent_slug": "coder"}]})).status_code == 409

        removed = await client.request("DELETE", f"{base}/b")
        assert removed.status_code == 200  # nothing names b explicitly: c depends on a
        assert (await client.request("DELETE", f"{base}/a")).status_code == 409  # a is completed
        assert (await client.request("DELETE", "/workflow-runs/missing/steps/a")).status_code == 404
        final = await client.get(f"/workflow-runs/{run_id}")
        assert final.json()["plan_revision"] == 3 and [s["key"] for s in final.json()["steps"]] == ["a", "c"]


# --- steps running at once, each in a worktree of its own ---------------------------------------------------------


def git_out(cwd: Path | str, *args: str) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    return subprocess.run(["git", *args], cwd=cwd, check=True, env=env, capture_output=True, text=True).stdout.strip()


def commit_file(repo: Path, name: str, text: str) -> None:
    (repo / name).write_text(text)
    git_out(repo, "add", "-A")
    git_out(repo, "commit", "-q", "-m", f"add {name}")


class Hold:
    """The faux executor with a delay or a gate per step, recording who ran at once and what each worktree held."""

    def __init__(self, faux: FauxExecutor, delay: float = 0.0) -> None:
        self.faux, self.delay = faux, delay
        self.gates: dict[str, asyncio.Event] = {}
        self.entered: dict[str, asyncio.Event] = {}
        self.active: set[str] = set()
        self.peak = 0
        self.spans: dict[str, list[float]] = {}
        self.seen: dict[str, dict[str, Any]] = {}

    def gate(self, *keys: str) -> None:
        for key in keys:
            self.gates[key] = asyncio.Event()
            self.entered[key] = asyncio.Event()

    async def run(self, packet, model, worktree, run_dir, on_event) -> StepResult:
        key = packet.step_key
        self.active.add(key)
        self.peak = max(self.peak, len(self.active))
        loop = asyncio.get_running_loop()
        self.spans[key] = [loop.time(), 0.0]
        self.seen[key] = {
            "worktree": str(worktree),
            "files": sorted(p.name for p in worktree.iterdir() if p.name != ".git"),
            "text": {p.name: p.read_text() for p in worktree.iterdir() if p.is_file() and p.name != ".git"},
        }
        try:
            if key in self.gates:
                self.entered[key].set()
                await self.gates[key].wait()
            else:
                await asyncio.sleep(self.delay)
            return await self.faux.run(packet, model, worktree, run_dir, on_event)
        finally:
            self.active.discard(key)
            self.spans[key][1] = loop.time()


def with_hold(world: World, delay: float = 0.1) -> Hold:
    hold = Hold(world.faux, delay)
    world.deps.get_executor = lambda _kind: hold
    return hold


def parallel(repo: Path, cap: int, *steps: dict[str, Any], **extra: Any) -> RunDefinition:
    policy = {"max_concurrent_steps": cap, **extra.pop("policy", {})}
    return graph(repo, *steps, policy=policy, **extra)


async def snapshot(world: World, pg_db: AsyncSession, run_id: str) -> dict[str, Any]:
    async with world.lock:
        return await view_of(pg_db, run_id)


async def watching(world: World, pg_db: AsyncSession, run_id: str, seen: list[dict[str, Any]], stop: asyncio.Event) -> None:
    while not stop.is_set():
        seen.append(await snapshot(world, pg_db, run_id))
        await asyncio.sleep(0.02)


def branches(repo: Path) -> list[str]:
    return git_out(repo, "branch", "--list", "--format=%(refname:short)").split()


async def test_with_a_cap_of_one_steps_run_one_at_a_time_in_the_run_worktree(pg_db, repo, world_factory) -> None:
    world = world_factory({"a": [FauxAction(write={"a.txt": "a\n"})], "b": [FauxAction(write={"b.txt": "b\n"})]})
    chains(world)
    hold = with_hold(world, 0.05)
    run_id, _ = await create_run(
        pg_db, graph(repo, {"key": "a", "depends_on": []}, {"key": "b", "depends_on": []}, {"key": "c", "depends_on": []}), deps=world.deps
    )
    assert (await world.run_to_stop(run_id))["reason"] == "completed"
    view = await view_of(pg_db, run_id)
    assert hold.peak == 1 and order(world) == ["a", "b", "c"]
    assert (view["max_concurrent_steps"], view["uses_lanes"], view["running_steps"]) == (1, False, [])
    # Everything happens in the run worktree on the run branch, as it always did; no lane exists.
    assert not (Path(view["worktree"]).parent / "lanes").exists() and branches(repo) == ["main", view["branch"]]
    assert {s["workspace"]["kind"] for s in view["steps"]} == {"run"}
    assert {s["workspace"]["worktree"] for s in view["steps"]} == {view["worktree"]}
    assert all((Path(view["worktree"]) / f"{n}.txt").exists() for n in "ab")  # one tree holds everything
    assert view["result"]["mode"] == "run_worktree" and view["result"]["state"] == "complete"
    assert view["result"]["branch"] == view["branch"] and view["result"]["sha"] == view["steps"][-1]["checkpoint_sha"]
    assert git_out(view["worktree"], "rev-parse", "HEAD") == view["result"]["sha"]


async def test_three_independent_steps_with_a_cap_of_two_never_have_more_than_two_running(pg_db, repo, world_factory) -> None:
    files = {k: [FauxAction(write={f"{k}.txt": f"{k}\n"})] for k in "abc"}
    world = world_factory(files)
    chains(world)
    hold = with_hold(world, 0.3)
    # Each step's own acceptance runs in its own lane: it sees its file and not the others'.
    accept = lambda k: [f"test -f {k}.txt && test $(ls *.txt | wc -l) = 1"]  # noqa: E731
    definition = parallel(repo, 2, *({"key": k, "depends_on": [], "acceptance": accept(k)} for k in "abc"))
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    seen: list[dict[str, Any]] = []
    stop = asyncio.Event()
    watcher = asyncio.create_task(watching(world, pg_db, run_id, seen, stop))
    try:
        results = await world.drive(run_id)
    finally:
        stop.set()
        await watcher
    assert {r["reason"] for r in results} >= {"completed"}
    view = await view_of(pg_db, run_id)
    assert view["state"] == "completed" and view["max_concurrent_steps"] == 2 and view["uses_lanes"]

    # At most two ran at once, and two really did: the first two overlap, the third starts after one of them ends.
    assert hold.peak == 2
    (a0, a1), (b0, b1), (c0, _c1) = (hold.spans[k] for k in "abc")
    assert max(a0, b0) < min(a1, b1) and c0 >= min(a1, b1)
    assert max(len(v["running_steps"]) for v in seen) == 2  # the run view never showed a third
    # A step's workspace is unknown until its lane exists, so look at the first view where both are placed.
    both = next(
        v
        for v in seen
        if len(v["running_steps"]) == 2 and all(s["workspace"] for s in v["steps"] if s["status"] == "running")
    )
    assert both["running_steps"] == ["a", "b"]
    lanes_now = [s["workspace"] for s in both["steps"] if s["status"] == "running"]
    assert len({w["worktree"] for w in lanes_now}) == 2 and len({w["branch"] for w in lanes_now}) == 2
    assert all(w["kind"] == "lane" and w["merge_result"] == "none" and w["base_sha"] == view["base_sha"] for w in lanes_now)

    # Each step ran on a branch named for the run and the step; its directory is gone, its commits are not.
    steps = {s["key"]: s for s in view["steps"]}
    for key, step in steps.items():
        assert step["workspace"]["branch"] == f"{view['branch']}-{key}" and step["workspace"]["retired"]
        assert not Path(step["workspace"]["worktree"]).exists()
        assert git_out(repo, "rev-parse", step["workspace"]["branch"]) == step["checkpoint_sha"]
    assert set(branches(repo)) >= {f"{view['branch']}-{k}" for k in "abc"}
    # Acceptance ran per step, in the step's own lane.
    for step in steps.values():
        (attempt,) = step["attempt_history"]
        assert [r["exit_code"] for r in attempt["acceptance"]] == [0] and attempt["workspace"]["lane"] == step["key"]
    # The result is all three steps' work on the run branch, in the run worktree.
    result = view["result"]
    assert (result["mode"], result["state"], result["merged"]) == ("lanes", "merged", ["a", "b", "c"])
    assert (result["branch"], result["worktree"]) == (view["branch"], view["worktree"])
    assert git_out(view["worktree"], "rev-parse", "HEAD") == result["sha"]
    assert all((Path(view["worktree"]) / f"{k}.txt").read_text() == f"{k}\n" for k in "abc")
    # Usage rolls up over the three steps' attempts.
    assert [a["usage"]["input_tokens"] for s in steps.values() for a in s["attempt_history"]] == [100, 100, 100]
    assert view["usage_totals"]["total_tokens"] == 360


async def test_a_join_after_branches_that_edited_different_files_merges_cleanly(pg_db, repo, world_factory) -> None:
    world = world_factory(
        {
            "a": [FauxAction(write={"a.txt": "a\n"})],
            "b": [FauxAction(write={"b.txt": "b\n"})],
            "join": [FauxAction(write={"joined.txt": "ok\n"})],
        }
    )
    chains(world)
    hold = with_hold(world, 0.1)
    definition = parallel(
        repo,
        2,
        {"key": "a", "depends_on": []},
        {"key": "b", "depends_on": []},
        {"key": "join", "depends_on": ["a", "b"], "acceptance": ["test -f a.txt && test -f b.txt"]},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.drive(run_id)
    view = await view_of(pg_db, run_id)
    steps = {s["key"]: s for s in view["steps"]}
    assert view["state"] == "completed" and hold.peak == 2
    assert "a.txt" in hold.seen["join"]["files"] and "b.txt" in hold.seen["join"]["files"]  # both branches' work
    ws = steps["join"]["workspace"]
    assert (ws["merge_result"], [m["result"] for m in ws["merges"]]) == ("clean", ["clean"])
    assert ws["base_sha"] == steps["a"]["checkpoint_sha"] and ws["parents"][1] == {"step": "b", "sha": steps["b"]["checkpoint_sha"]}
    assert ws["start_sha"] and ws["start_sha"] != ws["base_sha"] and ws["conflict_files"] == []
    assert "Merge conflicts" not in next(c["packet"] for c in world.faux.calls if c["step"] == "join")
    # The attempt keeps the merge result too; the join's checkpoint merges a and b.
    assert steps["join"]["attempt_history"][0]["workspace"]["merge_result"] == "clean"
    parents = git_out(repo, "rev-list", "--parents", "-n", "1", steps["join"]["checkpoint_sha"]).split()
    assert len(parents) == 2  # a plain commit on top of the merge
    assert git_out(repo, "rev-list", "--merges", "--count", steps["join"]["checkpoint_sha"]) == "1"
    # The join is the only leaf, so the run branch is exactly its checkpoint.
    assert view["result"]["sha"] == steps["join"]["checkpoint_sha"] and view["result"]["merged"] == ["join"]
    assert all((Path(view["worktree"]) / n).exists() for n in ("a.txt", "b.txt", "joined.txt"))
    # Its acceptance (both files in its own tree) passed.
    assert [r["exit_code"] for r in steps["join"]["attempt_history"][0]["acceptance"]] == [0]


async def test_a_join_after_edits_to_the_same_lines_gets_the_conflict_and_a_packet_section(pg_db, repo, world_factory) -> None:
    commit_file(repo, "shared.txt", "one\ntwo\nthree\n")
    world = world_factory(
        {
            "a": [FauxAction(write={"shared.txt": "one\nTWO by a\nthree\n"})],
            "b": [FauxAction(write={"shared.txt": "one\nTWO by b\nthree\n"})],
            # The first attempt leaves the markers in; the second resolves them.
            "join": [FauxAction(), FauxAction(write={"shared.txt": "one\nTWO by a and b\nthree\n"})],
        }
    )
    chains(world)
    hold = with_hold(world, 0.1)
    definition = parallel(
        repo,
        2,
        {"key": "a", "depends_on": []},
        {"key": "b", "depends_on": []},
        {"key": "join", "depends_on": ["a", "b"], "acceptance": ["! grep -q '<<<<<<<' shared.txt"]},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.drive(run_id)
    view = await view_of(pg_db, run_id)
    steps = {s["key"]: s for s in view["steps"]}
    ws = steps["join"]["workspace"]
    assert (ws["merge_result"], ws["conflict_files"], ws["start_sha"]) == ("conflict", ["shared.txt"], None)
    assert [(m["step"], m["result"]) for m in ws["merges"]] == [("b", "conflict")]
    # The step was given the conflicted tree (not a resolved one) and told which files to resolve first.
    first = hold.seen["join"]["text"]["shared.txt"]
    assert "<<<<<<<" in first and "TWO by a" in first and "TWO by b" in first
    packets = [c["packet"] for c in world.faux.calls if c["step"] == "join"]
    assert len(packets) == 2  # the markers left in the first attempt kept it from being checkpointed
    for packet in packets:
        section = packet.split("# Merge conflicts to resolve first", 1)[1].split("\n\n# ", 1)[0]
        assert "- shared.txt" in section and "conflict marker" in section
    first_attempt, second_attempt = steps["join"]["attempt_history"]
    assert first_attempt["status"] == "failed" and first_attempt["decision"]["reason"] == "acceptance_failed"
    assert [r["passed"] for r in first_attempt["acceptance"]] == [False]
    # The retry kept the same lane (one merge result, one base) and finished the merge.
    assert second_attempt["workspace"]["base_sha"] == first_attempt["workspace"]["base_sha"]
    assert view["state"] == "completed" and steps["join"]["status"] == "completed"
    parents = git_out(repo, "rev-list", "--parents", "-n", "1", steps["join"]["checkpoint_sha"]).split()[1:]
    assert parents == [steps["a"]["checkpoint_sha"], steps["b"]["checkpoint_sha"]]
    assert git_out(repo, "show", f"{steps['join']['checkpoint_sha']}:shared.txt") == "one\nTWO by a and b\nthree"
    assert view["result"]["state"] == "merged" and view["result"]["sha"] == steps["join"]["checkpoint_sha"]


async def test_cancelling_one_parallel_step_leaves_the_others_running(pg_db, repo, world_factory) -> None:
    world = world_factory({k: [FauxAction(write={f"{k}.txt": f"{k}\n"})] for k in "abc"})
    chains(world)
    hold = with_hold(world)
    hold.gate("a", "b")
    definition = parallel(
        repo, 2, *({"key": k, "depends_on": []} for k in "abc"),
        policy={"heartbeat_interval_seconds": 0.1, "process_stop_grace_seconds": 0.3},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.spawn(run_id)
    await asyncio.wait_for(asyncio.gather(hold.entered["a"].wait(), hold.entered["b"].wait()), 20)
    async with world.lock:
        asked = await cancel_step(pg_db, run_id, "a", CancelRequest(reason="not needed"), deps=world.deps)
    assert asked["cancelling"]
    await asyncio.wait_for(hold.entered["c"].wait() if "c" in hold.entered else _until(lambda: "c" in hold.seen), 20)
    # a was stopped and c took its slot; b was never touched and still runs.
    view = await snapshot(world, pg_db, run_id)
    status = {s["key"]: s["status"] for s in view["steps"]}
    assert status == {"a": "cancelled", "b": "running", "c": "running"} or status["b"] == "running"
    assert view["state"] == "running" and "b" in hold.active and hold.peak == 2
    hold.gates["b"].set()
    await world.settle()
    view = await view_of(pg_db, run_id)
    assert {s["key"]: s["status"] for s in view["steps"]} == {"a": "cancelled", "b": "completed", "c": "completed"}
    assert view["state"] == "completed" and view["steps"][0]["attempt_history"][0]["outcome"]["kind"] == "cancelled"
    # The cancelled step has no checkpoint; the others' work is the result.
    assert view["result"]["merged"] == ["b", "c"] and not (Path(view["worktree"]) / "a.txt").exists()


async def _until(check, within: float = 20) -> None:
    deadline = asyncio.get_running_loop().time() + within
    while not check():
        assert asyncio.get_running_loop().time() < deadline, "condition not reached"
        await asyncio.sleep(0.02)


async def test_cancelling_the_run_stops_every_running_step_and_the_last_one_ends_it(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    hold = with_hold(world)
    hold.gate("a", "b")
    definition = parallel(
        repo, 2, *({"key": k, "depends_on": []} for k in "abc"),
        policy={"heartbeat_interval_seconds": 0.1, "process_stop_grace_seconds": 0.3},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.spawn(run_id)
    await asyncio.wait_for(asyncio.gather(hold.entered["a"].wait(), hold.entered["b"].wait()), 20)
    async with world.lock:
        await cancel_run(pg_db, run_id, CancelRequest(reason="stop all"), deps=world.deps)
    await world.settle()
    view = await view_of(pg_db, run_id)
    assert view["state"] == "cancelled" and [s["status"] for s in view["steps"]] == ["cancelled", "cancelled", "skipped"]
    assert hold.active == set() and "c" not in hold.seen


async def test_a_failing_step_stops_the_steps_running_beside_it(pg_db, repo, world_factory) -> None:
    world = world_factory({"a": [FauxAction("error")]})
    chains(world)
    hold = with_hold(world)
    hold.gate("b")
    definition = parallel(
        repo, 2, {"key": "a", "depends_on": [], "max_attempts": 1}, {"key": "b", "depends_on": []},
        policy={"heartbeat_interval_seconds": 0.1, "process_stop_grace_seconds": 0.3},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.spawn(run_id)
    await world.settle(30)  # b is gated: it ends only because the run failed under it
    view = await view_of(pg_db, run_id)
    assert view["state"] == "failed" and [s["status"] for s in view["steps"]] == ["failed", "cancelled"]
    assert "run failed" in view["steps"][1]["cancel"]["reason"] and hold.active == set()


async def test_recovery_after_a_crash_with_two_steps_running_restarts_both_on_their_own_worktrees(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"a": [FauxAction(write={"a.txt": "a\n"})], "b": [FauxAction(write={"b.txt": "b\n"})]})
    chains(world)
    hold = with_hold(world, 0.05)
    definition = parallel(
        repo, 2, {"key": "a", "depends_on": []}, {"key": "b", "depends_on": []},
        policy={"stale_after_seconds": 100, "process_stop_grace_seconds": 3},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    # The worker dies with both steps running: two attempts, two lanes with half-written files, an orphan each.
    _early, first = await engine_module._commit_intent(run_id, world.deps)
    _early, second = await engine_module._commit_intent(run_id, world.deps)
    assert first is not None and second is not None and first.lane == "a" and second.lane == "b" and first.more
    assert first.attempt_id != second.attempt_id
    orphans: dict[str, subprocess.Popen] = {}
    children: dict[str, int] = {}
    bystander = subprocess.Popen(
        [sys.executable, "-c", TREE], start_new_session=True, stdout=subprocess.PIPE, text=True,
        env={**os.environ, MARKER_ENV: "some-other-attempt"},
    )
    try:
        for intent in (first, second):
            record = await engine_module._prepare_lane(intent, engine_module._workspace_of(intent, engine_module.load_policy(intent.meta["policy"])), world.deps)
            (Path(record["worktree"]) / "half-written.txt").write_text("partial")
            orphan = subprocess.Popen(
                [sys.executable, "-c", TREE], start_new_session=True, stdout=subprocess.PIPE, text=True,
                env={**os.environ, MARKER_ENV: intent.attempt_id},
            )
            orphans[intent.step_key] = orphan
            assert orphan.stdout is not None
            children[intent.step_key] = json.loads(orphan.stdout.readline())["child"]
            identity = identify(orphan.pid)
            assert identity is not None
            await engine_module._record_process(world.deps, intent.attempt_id, {"kind": "harness", **identity.as_dict()})
        assert bystander.stdout is not None
        bystander_child = json.loads(bystander.stdout.readline())["child"]

        world.clock += 500
        assert await recover_stale_steps(world.deps) == [run_id]  # one advance is enough: it queues the next
        for key in "ab":  # each orphan group was stopped through its own attempt
            assert orphans[key].wait(timeout=10) != 0 and await gone(children[key], within=5)
        assert running(bystander.pid) and running(bystander_child)  # another attempt's marker: never touched
        view = await view_of(pg_db, run_id)
        for step, intent in zip(view["steps"], (first, second), strict=True):
            (attempt,) = step["attempt_history"]
            assert step["status"] == "pending" and attempt["session_id"] == intent.attempt_id
            assert [p["recovery"] for p in attempt["processes"]] == ["terminated"]
            assert attempt["processes"][0]["pid"] == orphans[step["key"]].pid
        lane_a = Path(view["steps"][0]["workspace"]["worktree"])
        assert lane_a != Path(view["steps"][1]["workspace"]["worktree"]) and (lane_a / "half-written.txt").exists()

        await world.drive(run_id)
        view = await view_of(pg_db, run_id)
        assert view["state"] == "completed" and [s["restarts"] for s in view["steps"]] == [1, 1]
        # Each restarted in its own lane, reset to where it started (the half-written file is gone).
        assert hold.seen["a"]["worktree"] != hold.seen["b"]["worktree"]
        assert all("half-written.txt" not in hold.seen[k]["files"] for k in "ab")
        assert hold.seen["a"]["worktree"].endswith("/lanes/a") and hold.seen["b"]["worktree"].endswith("/lanes/b")
        assert view["result"]["merged"] == ["a", "b"]
    finally:
        for process in (bystander, *orphans.values()):
            if process.poll() is None:
                process.kill()
                process.wait()


async def test_a_pending_step_can_be_revised_while_others_run_and_a_higher_cap_starts_it(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    hold = with_hold(world)
    hold.gate("a", "b")
    definition = parallel(
        repo, 2, {"key": "a", "depends_on": []}, {"key": "b", "depends_on": []}, {"key": "c", "depends_on": ["a"]}
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await world.spawn(run_id)
    await asyncio.wait_for(asyncio.gather(hold.entered["a"].wait(), hold.entered["b"].wait()), 20)
    async with world.lock:
        effort = await revise_step(pg_db, run_id, "c", StepRevision(effort="high"), deps=world.deps)
        assert (effort["changed"], effort["enqueue"]) == (True, False)  # both slots are busy
        freed = await revise_step(pg_db, run_id, "c", StepRevision(depends_on=[]), deps=world.deps)
        assert freed["enqueue"] is False  # ready now, but the cap is full
        # A running step cannot be revised, as before.
        with pytest.raises(WorkflowRunError) as started:
            await revise_step(pg_db, run_id, "a", StepRevision(effort="low"), deps=world.deps)
        assert started.value.code == "step_not_pending"
        same = await revise_run(pg_db, run_id, RunRevision(max_concurrent_steps=2), deps=world.deps)
        assert same["changed"] is False
        raised = await revise_run(
            pg_db, run_id, RunRevision(max_concurrent_steps=3, changed_by="coordinator", reason="room for c"), deps=world.deps
        )
    assert (raised["changed"], raised["enqueue"], raised["plan_revision"]) == (True, True, 3)
    await world.spawn(run_id)  # what the API does with enqueue
    await _until(lambda: "c" in hold.seen)
    assert hold.peak == 3 and {"a", "b", "c"} <= hold.active | set(hold.seen)
    for gate in hold.gates.values():
        gate.set()
    await world.settle()
    view = await view_of(pg_db, run_id)
    assert view["state"] == "completed" and view["max_concurrent_steps"] == 3
    history = view["plan_history"]
    assert [h["action"] for h in history] == ["revise_step", "revise_step", "revise_run"]
    assert history[2]["changes"][0]["after"] == {"max_concurrent_steps": 3} and history[2]["by"]["changed_by"] == "coordinator"
    assert view["steps"][2]["effort"] == "high"


async def test_the_cap_is_set_at_create_and_a_run_without_a_repository_cannot_raise_it(pg_db, repo, world_factory) -> None:
    world = world_factory({})
    chains(world)
    with pytest.raises(ValueError, match="needs a repo_path"):
        await create_run(
            pg_db,
            RunDefinition(
                goal="x", project_id="p", policy={"max_concurrent_steps": 2},
                steps=[{"key": "a", "instructions": "x", "agent_slug": "coder", "executor": "faux"}],
            ),
            deps=world.deps,
        )
    with pytest.raises(ValueError, match="max_concurrent_steps"):
        await create_run(pg_db, parallel(repo, 0, {"key": "a"}), deps=world.deps)
    plain = RunDefinition(
        goal="x", project_id="p", steps=[{"key": "a", "instructions": "x", "agent_slug": "coder", "executor": "faux"}]
    )
    run_id, _ = await create_run(pg_db, plain, deps=world.deps)
    with pytest.raises(WorkflowRunError) as refused:
        await revise_run(pg_db, run_id, RunRevision(max_concurrent_steps=2), deps=world.deps)
    assert refused.value.code == "invalid_plan"
    run_id, _ = await create_run(pg_db, parallel(repo, 3, {"key": "a"}), deps=world.deps)
    assert (await view_of(pg_db, run_id))["max_concurrent_steps"] == 3


async def test_a_run_that_starts_on_the_run_worktree_moves_to_lanes_when_the_cap_is_raised(pg_db, repo, world_factory) -> None:
    world = world_factory({k: [FauxAction(write={f"{k}.txt": f"{k}\n"})] for k in "abc"})
    chains(world)
    hold = with_hold(world, 0.05)
    definition = graph(repo, {"key": "a", "depends_on": []}, {"key": "b", "depends_on": ["a"]}, {"key": "c", "depends_on": []})
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await advance_run(run_id, deps=world.deps)  # a: one at a time, in the run worktree
    view = await view_of(pg_db, run_id)
    assert view["steps"][0]["workspace"]["kind"] == "run" and not view["uses_lanes"]
    await revise_run(pg_db, run_id, RunRevision(max_concurrent_steps=2), deps=world.deps)
    await world.drive(run_id)
    view = await view_of(pg_db, run_id)
    steps = {s["key"]: s for s in view["steps"]}
    assert view["state"] == "completed" and view["uses_lanes"] and hold.peak == 2
    assert steps["b"]["workspace"]["kind"] == "lane" and steps["b"]["workspace"]["base_sha"] == steps["a"]["checkpoint_sha"]
    assert steps["c"]["workspace"]["base_sha"] == view["base_sha"]  # independent of a: starts from the run's base
    assert "a.txt" in hold.seen["b"]["files"] and "a.txt" not in hold.seen["c"]["files"]
    assert view["result"]["mode"] == "lanes" and view["result"]["merged"] == ["b", "c"]
    assert all((Path(view["worktree"]) / f"{k}.txt").exists() for k in "abc")


async def test_revising_the_dependencies_of_a_step_whose_lane_exists_makes_the_lane_again(pg_db, repo, world_factory) -> None:
    world = world_factory(
        {"a": [FauxAction(write={"a.txt": "a\n"})], "b": [FauxAction(write={"b.txt": "b\n"})], "c": [FauxAction("error"), FauxAction()]}
    )
    chains(world)
    hold = with_hold(world, 0.0)

    async def one_at_a_time(_run_id: str) -> None:
        return None

    world.deps.enqueue_advance = one_at_a_time  # the test takes the advances itself, in order
    definition = parallel(repo, 2, {"key": "a", "depends_on": []}, {"key": "b", "depends_on": []}, {"key": "c", "depends_on": ["a"]})
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)
    await advance_run(run_id, deps=world.deps)  # a
    await advance_run(run_id, deps=world.deps)  # b
    await advance_run(run_id, deps=world.deps)  # c fails once, keeping its lane
    first = (await view_of(pg_db, run_id))["steps"][2]["workspace"]
    assert first["parents"][0]["step"] == "a" and Path(first["worktree"]).exists()
    await revise_step(pg_db, run_id, "c", StepRevision(depends_on=["a", "b"]), deps=world.deps)
    await world.drive(run_id)
    view = await view_of(pg_db, run_id)
    again = view["steps"][2]["workspace"]
    assert [p["step"] for p in again["parents"]] == ["a", "b"] and again["merge_result"] == "clean"
    assert "b.txt" in hold.seen["c"]["files"] and view["state"] == "completed"
