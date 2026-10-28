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
from app.services.workflow_runs.policy import Unavailable
from app.services.workflow_runs.processes import MARKER_ENV, identify, read_stat
from app.services.workflow_runs.schemas import (
    AcceptanceCommand,
    CancelRequest,
    OwnerDecision,
    RunDefinition,
    StepTestHooks,
)
from app.services.workflow_runs.workspace import RunWorkspace

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
    limit = FauxAction("usage_limit", resets_at=int(NOW) + 60)
    world = world_factory({"plan": [limit]})
    world.chains.update({slug: [OPUS] for slug in ("planner", "coder", "reviewer")})
    definition = example(
        "plan-implement-review-fix",
        repo,
        policy={"max_usage_limit_resumes": 1, "max_total_attempts": 4},
    )
    run_id, _ = await create_run(pg_db, definition, deps=world.deps)

    async def pass_the_reset() -> bool:
        world.clock += 120
        world.unavailable.clear()
        return run_id in await recover_stale_steps(world.deps)

    assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_wait"  # attempt 1
    assert await pass_the_reset()  # the one allowed automatic resume
    assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_resume_limit"  # attempt 2
    assert not await pass_the_reset()  # no more automatic resumes: the owner decides
    view = await view_of(pg_db, run_id)
    assert view["steps"][0]["usage_limit_resumes"] == 1 and view["state"] == "needs_owner"

    await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)  # fresh counters
    assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_wait"  # attempt 3
    assert await pass_the_reset()
    assert (await world.run_to_stop(run_id))["reason"] == "usage_limit_resume_limit"  # attempt 4
    view = await view_of(pg_db, run_id)
    assert view["steps"][0]["attempts"] == 4 == view["limits"]["max_total_attempts"]
    with pytest.raises(WorkflowRunError, match="has used its attempts") as raised:
        await resume_run(pg_db, run_id, OwnerDecision(action="retry"), deps=world.deps)
    assert raised.value.code == "attempt_limit"
    # The owner can still end the run.
    ended = await resume_run(pg_db, run_id, OwnerDecision(action="fail"), deps=world.deps)
    assert ended["state"] == "failed"
    assert len(world.faux.calls) == 4


async def test_usage_limit_cycling_alone_fails_the_step_at_max_total_attempts(
    pg_db, repo, world_factory
) -> None:
    world = world_factory({"plan": [FauxAction("usage_limit", resets_at=int(NOW) + 60)]})
    world.chains.update({slug: [OPUS] for slug in ("planner", "coder", "reviewer")})
    definition = example(
        "plan-implement-review-fix",
        repo,
        policy={"max_usage_limit_resumes": 99, "max_total_attempts": 3},
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
            "message": "run is already completed",
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
