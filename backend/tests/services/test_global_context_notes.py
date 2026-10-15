"""Attribution of prompt/agent/memory writes and the note for context every agent receives."""

from __future__ import annotations

import argparse
import asyncio
import contextvars
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.core.request_actor import attribute, bind_request_actor, current_request_actor
from app.middleware.access_control_handler_helpers import set_identified_state
from app.middleware.access_control_handlers import set_internal_state
from app.models.memory_unified import Memory
from app.models.prompt import Prompt, PromptRevision
from app.services import global_context_notes
from app.services.global_context_notes import GlobalContextNote, queue_global_context_note
from app.services.memory._repo_revisions import RevisionRepository
from app.services.prompt_service import record_prompt_revision
from tests.conftest import create_mock_db_session


def _isolated(fn: Any, *args: Any) -> Any:
    """Run with a fresh context so a bound actor never leaks into other tests."""
    return contextvars.Context().run(fn, *args)


def _request(headers: dict[str, str]) -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    return Request({"type": "http", "method": "PUT", "path": "/api/prompts/x", "headers": raw})


def test_attribute_names_the_calling_client() -> None:
    def run() -> tuple[str | None, ...]:
        before = attribute("api")
        bind_request_actor(client_id="086e0410", request_source="st-memory", internal=False)
        return before, attribute("api"), attribute(None), attribute("save_learning"), attribute("persona")

    before, api, none, label, persona = _isolated(run)
    assert before == "api"  # outside a request labels pass through
    assert api == none == "client:086e0410/st-memory"
    assert label == "save_learning via client:086e0410/st-memory"
    assert persona == "persona via client:086e0410/st-memory"


def test_middleware_binds_identified_and_internal_callers() -> None:
    def identified() -> str | None:
        set_identified_state(_request({}), {"id": "086e0410", "allowed_projects": None}, "st-cli")
        return current_request_actor()

    def internal() -> str | None:
        set_internal_state(_request({"X-Client-Id": "dash", "X-Request-Source": "agent-hub-dashboard"}))
        return current_request_actor()

    assert _isolated(identified) == "client:086e0410/st-cli"
    assert _isolated(internal) == "internal:dash/agent-hub-dashboard"


def _prompt(**overrides: Any) -> Prompt:
    prompt = Prompt(slug="safety-directive", name="Safety Directive", content="Never expose secrets.\nAsk first.",
                    is_global=True, enabled=True, exclude_agents=[], prompt_type="global_guardrail", deletion_locked=True)
    prompt.id = 7
    for key, value in overrides.items():
        setattr(prompt, key, value)
    return prompt


def _db_with_previous(previous: object | None) -> MagicMock:
    db = create_mock_db_session()
    db.execute.return_value.scalar_one_or_none.return_value = previous
    db.sync_session = Session()
    return db


async def test_global_prompt_change_queues_one_note_with_diff_and_client() -> None:
    previous = PromptRevision(content="Never expose secrets.\nAsk the owner first.", is_global=True, enabled=True,
                              exclude_agents=[])
    db = _db_with_previous(previous)

    async def run() -> None:
        bind_request_actor(client_id="086e0410", request_source="st-memory", internal=False)
        await record_prompt_revision(db, _prompt(), action="update", changed_by="api", change_reason="Trim")

    await asyncio.create_task(run(), context=contextvars.Context())

    revision = db.add.call_args.args[0]
    assert revision.changed_by == "client:086e0410/st-memory"
    (note,) = db.sync_session.info["global_context_notes"]
    assert note.title == "Global prompt edited"
    message = note.message()
    assert message.startswith("safety-directive was edited by client:086e0410/st-memory. Every agent receives it.")
    assert "Reason: Trim" in message
    assert "-Ask the owner first." in message and "+Ask first." in message
    assert "—" not in message


async def test_unglobaling_or_disabling_a_global_prompt_is_noted() -> None:
    previous = PromptRevision(content="Rules.", is_global=True, enabled=True, exclude_agents=[])
    db = _db_with_previous(previous)

    await record_prompt_revision(db, _prompt(content="Rules.", is_global=False, enabled=False), action="update")

    (note,) = db.sync_session.info["global_context_notes"]
    assert "enabled: True -> False" in note.flags
    assert "is_global: True -> False" in note.flags


async def test_non_global_prompt_and_metadata_only_edits_send_nothing() -> None:
    db = _db_with_previous(None)
    await record_prompt_revision(db, _prompt(is_global=False, prompt_type="standard"), action="update")
    assert "global_context_notes" not in db.sync_session.info

    same = PromptRevision(content="Never expose secrets.\nAsk first.", is_global=True, enabled=True, exclude_agents=[])
    db = _db_with_previous(same)
    await record_prompt_revision(db, _prompt(description="new words"), action="update")
    assert "global_context_notes" not in db.sync_session.info


def _memory(**overrides: Any) -> Memory:
    memory = Memory(id=UUID("12345678-0000-0000-0000-000000000000"), content="Never run sudo.", name="m",
                    summary="No sudo", scope="global", scope_id=None, tier=1, status="active", version=2, tags=[],
                    applicability={}, trigger_task_types=[], trigger_phases=[], metadata_={})
    for key, value in overrides.items():
        setattr(memory, key, value)
    return memory


def _memory_revision(**overrides: Any) -> SimpleNamespace:
    fields = {"content": "Never run sudo.", "scope": "global", "tier": 1, "status": "active", "applicability": {},
              "trigger_task_types": [], "trigger_phases": [], "render_mode": None, "metadata_": {}}
    return SimpleNamespace(**{**fields, **overrides})


async def test_global_mandate_memory_change_is_noted_and_demotion_too() -> None:
    previous = _memory_revision()
    db = _db_with_previous(previous)
    await RevisionRepository().record_revision(db, _memory(tier=3), action="update", changed_by="api")

    (note,) = db.sync_session.info["global_context_notes"]
    assert note.title == "Global mandate memory edited"
    assert note.name == "No sudo (12345678)"
    assert "tier: 1 -> 3" in note.flags

    db = _db_with_previous(None)
    await RevisionRepository().record_revision(db, _memory(scope="project", scope_id="x"), action="create")
    assert "global_context_notes" not in db.sync_session.info


@pytest.mark.parametrize(("change", "flag"), [
    ({"applicability": {"exclude_consumer_profiles": ["codex"]}},
     "applicability: {} -> {'exclude_consumer_profiles': ['codex']}"),
    ({"trigger_task_types": ["bug"]}, "trigger_task_types: [] -> ['bug']"),
    ({"trigger_phases": ["verify"]}, "trigger_phases: [] -> ['verify']"),
    ({"render_mode": "summary"}, "render_mode: None -> summary"),
    ({"metadata_": {"disclosure": {"workflows": ["w"], "activation": "triggered"}}},
     "disclosure: None -> {'workflows': ['w'], 'activation': 'triggered'}"),
])
async def test_retargeting_a_global_mandate_memory_is_noted(change: dict[str, Any], flag: str) -> None:
    db = _db_with_previous(_memory_revision())
    await RevisionRepository().record_revision(db, _memory(**change), action="context_edit", changed_by="api")

    (note,) = db.sync_session.info["global_context_notes"]
    assert note.flags == (flag,)
    assert db.add.call_args.args[0].render_mode == change.get("render_mode")

    db = _db_with_previous(_memory_revision(**change))
    await RevisionRepository().record_revision(db, _memory(**change), action="context_edit", changed_by="api")
    assert "global_context_notes" not in db.sync_session.info


@pytest.mark.parametrize(("policy", "flag"), [
    ({"scope": "global", "applicability": {"exclude_consumer_profiles": ["codex", "claude_code"]}},
     "policy applicability: {} -> {'exclude_consumer_profiles': ['codex', 'claude_code']}"),
    ({"scope": "global", "activation": "triggered", "task_types": ["bug"]}, "policy activation: always -> triggered"),
    ({"scope": "global", "workflows": ["w"]}, "policy workflows: [] -> ['w']"),
    ({"scope": "project", "targets": ["agent-hub"]}, "policy scope: global -> project"),
])
async def test_retargeting_or_triggering_a_global_prompt_is_noted(policy: dict[str, Any], flag: str) -> None:
    unchanged = {"scope": "global"}
    db = _db_with_previous(PromptRevision(content="Never expose secrets.\nAsk first.", is_global=True, enabled=True,
                                          exclude_agents=[], context_policy=unchanged, prompt_type="global_guardrail"))
    await record_prompt_revision(db, _prompt(context_policy=policy), action="context_edit")

    (note,) = db.sync_session.info["global_context_notes"]
    assert flag in note.flags
    assert note.message().startswith("safety-directive was edited by")


async def test_a_policy_scoped_global_prompt_counts_as_global() -> None:
    previous = PromptRevision(content="Rules.", is_global=False, enabled=True, exclude_agents=[],
                              context_policy={"scope": "global"}, prompt_type="standard")
    db = _db_with_previous(previous)
    policy = {"scope": "global", "applicability": {"consumer_profiles": ["dashboard"]}}
    await record_prompt_revision(db, _prompt(content="Rules.", is_global=False, prompt_type="standard",
                                             context_policy=policy), action="update")
    (note,) = db.sync_session.info["global_context_notes"]
    assert note.flags == ("policy applicability: {} -> {'consumer_profiles': ['dashboard']}",)


async def test_notes_go_out_after_commit_and_never_after_rollback() -> None:
    note = GlobalContextNote(kind="Global prompt", name="p", action="update", changed_by="c", before="a", after="b")
    sent: list[GlobalContextNote] = []

    async def fake_send(n: GlobalContextNote) -> None:
        sent.append(n)

    with patch.object(global_context_notes, "send_note", fake_send):
        session = Session()
        db = SimpleNamespace(sync_session=session)
        session.begin()
        queue_global_context_note(cast(AsyncSession, db), note)
        session.rollback()
        session.commit()
        queue_global_context_note(cast(AsyncSession, db), note)
        session.commit()
        await asyncio.gather(*list(global_context_notes._tasks))

    assert sent == [note]


async def test_send_note_is_an_info_push_without_tap_or_cooldown() -> None:
    process = MagicMock(returncode=0)
    process.communicate = AsyncMock(return_value=(None, b""))
    note = GlobalContextNote(kind="Global prompt", name="safety-directive", action="update", changed_by="c",
                             before="a", after="b")
    with (patch.object(global_context_notes.shutil, "which", return_value="/bin/nightshift"),
          patch.object(global_context_notes, "create_process", AsyncMock(return_value=process)) as create):
        await global_context_notes.send_note(note)

    assert create.await_args is not None
    args = create.await_args.args
    assert args[:2] == ("/bin/nightshift", "push")
    assert args[args.index("--severity") + 1] == "info"
    assert args[args.index("--cooldown") + 1] == "0"
    assert args[args.index("--key") + 1] == "agent-hub.global-context.prompt.safety-directive"
    assert args[-1] == note.message()


@pytest.mark.parametrize("failure", [OSError("missing"), None])
async def test_send_note_failure_never_raises(failure: OSError | None) -> None:
    note = GlobalContextNote(kind="Global prompt", name="p", action="update", changed_by="c", before="a", after="b")
    process = MagicMock(returncode=1)
    process.communicate = AsyncMock(return_value=(None, b"boom"))
    create = AsyncMock(side_effect=failure) if failure else AsyncMock(return_value=process)
    with (patch.object(global_context_notes.shutil, "which", return_value="/bin/nightshift"),
          patch.object(global_context_notes, "create_process", create)):
        await global_context_notes.send_note(note)


def test_actor_bound_in_middleware_reaches_the_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from app.middleware import access_control_paths
    from app.middleware.access_control import AccessControlMiddleware

    monkeypatch.setattr(access_control_paths.settings, "internal_service_secret", "s3cret")
    inner = FastAPI()

    @inner.put("/api/whoami")
    async def whoami() -> dict[str, str | None]:
        return {"actor": current_request_actor(), "attributed": attribute("api")}

    inner.add_middleware(AccessControlMiddleware)
    with patch("app.middleware.access_control.schedule_ui_request_log"):
        response = TestClient(inner).put(
            "/api/whoami", headers={"X-Agent-Hub-Internal": "s3cret", "X-Client-Id": "c1", "X-Request-Source": "st-cli"}
        )
    assert response.json() == {"actor": "internal:c1/st-cli", "attributed": "internal:c1/st-cli"}


async def test_send_note_ends_options_before_the_message() -> None:
    """A summary like '--key=x' must stay the message, not become an option that drops the note."""
    process = MagicMock(returncode=0)
    process.communicate = AsyncMock(return_value=(None, b""))
    note = GlobalContextNote(kind="Global mandate memory", name="--key=x (12345678)", action="update",
                             changed_by="c", before="a", after="b")
    with (patch.object(global_context_notes.shutil, "which", return_value="/bin/nightshift"),
          patch.object(global_context_notes, "create_process", AsyncMock(return_value=process)) as create):
        await global_context_notes.send_note(note)

    assert create.await_args is not None
    args = create.await_args.args
    assert args[-2:] == ("--", note.message())
    assert note.message().startswith("--key=x")
    parser = argparse.ArgumentParser()  # same shape as `nightshift push`
    for option in ("--severity", "--title", "--key", "--cooldown", "--open"):
        parser.add_argument(option)
    parser.add_argument("message")
    assert parser.parse_args(list(args[2:])).message == note.message()


def _db_returning(rows: list[object]) -> MagicMock:
    db = create_mock_db_session()
    db.execute.return_value.scalars.return_value = rows
    db.sync_session = Session()
    return db


def _placement(source_id: str, mode: str = "exclude", enabled: bool = True, source_type: str = "prompt") -> dict[str, Any]:
    return {"source_type": source_type, "source_id": source_id, "mode": mode, "enabled": enabled}


async def test_excluding_a_global_prompt_for_every_project_is_noted_once() -> None:
    db = _db_returning([_prompt()])
    await global_context_notes.queue_exclusion_notes(
        cast(AsyncSession, db), consumer_profile="codex", project_id=None, before=[_placement("other", "include")],
        after=[_placement("safety-directive"), _placement("other", "include")], changed_by="internal:c1/st-cli",
    )

    (note,) = db.sync_session.info["global_context_notes"]
    assert note.title == "Global prompt excluded"
    assert note.key == "agent-hub.global-context.prompt.safety-directive"
    assert note.message() == ("safety-directive was excluded from codex context in every project by internal:c1/st-cli. "
                              "Those agents no longer receive it.")


async def test_exclusion_notes_name_the_project_and_global_mandate_memories() -> None:
    db = _db_returning([_memory()])
    await global_context_notes.queue_exclusion_notes(
        cast(AsyncSession, db), consumer_profile="claude_code", project_id="neri", before=[],
        after=[_placement("12345678-0000-0000-0000-000000000000", source_type="memory")], changed_by=None,
    )
    (note,) = db.sync_session.info["global_context_notes"]
    assert note.title == "Global mandate memory excluded"
    assert note.message().startswith("No sudo (12345678) was excluded from claude_code context in project neri by an "
                                     "unidentified caller.")


async def test_unchanged_disabled_or_included_placements_send_nothing() -> None:
    db = _db_returning([_prompt()])
    await global_context_notes.queue_exclusion_notes(
        cast(AsyncSession, db), consumer_profile="codex", project_id=None,
        before=[_placement("safety-directive")],
        after=[_placement("safety-directive"), _placement("a", enabled=False), _placement("b", "include"),
               _placement("not-a-uuid", source_type="memory")],
        changed_by="c",
    )
    db.execute.assert_not_called()
    assert "global_context_notes" not in db.sync_session.info


async def test_exclusion_query_keeps_only_global_prompts() -> None:
    db = _db_returning([])
    await global_context_notes.queue_exclusion_notes(
        cast(AsyncSession, db), consumer_profile="codex", project_id=None, before=[],
        after=[_placement("project-only-prompt")], changed_by="c",
    )
    statement = str(db.execute.await_args.args[0])
    assert "prompts.is_global IS true OR prompts.prompt_type IN" in statement
    assert "global_context_notes" not in db.sync_session.info
