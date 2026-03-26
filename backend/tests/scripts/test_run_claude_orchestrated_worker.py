from __future__ import annotations

import asyncio
import importlib.util
import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "run_claude_orchestrated_worker.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("run_claude_orchestrated_worker", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_build_claude_command_uses_stdin_input_without_prompt_arg(tmp_path):
    module = _load_module()

    command = module._build_claude_command(
        schema_path=None,
        agents_path=None,
        agents_payload=None,
        model="sonnet",
        allowed_tools="Read,Agent",
        permission_mode="bypassPermissions",
    )

    assert command[:6] == [
        "claude",
        "--print",
        "--verbose",
        "--input-format",
        "text",
        "--output-format",
    ]
    assert "Read,Agent" in command
    assert "Reply with the single word hi." not in command


def test_run_text_command_strips_pythonpath_for_nested_st_calls(tmp_path):
    module = _load_module()
    captured: dict[str, object] = {}

    def _fake_run(*args, **kwargs):
        captured["env"] = kwargs["env"]
        return SimpleNamespace(stdout="TASK:task-123|pending|P2|refactor|SIMPLE\n")

    with (
        patch.dict(module.os.environ, {"PYTHONPATH": "backend", "KEEP_ME": "1"}, clear=True),
        patch.object(module.subprocess, "run", side_effect=_fake_run),
    ):
        output = module._run_text_command(command=["st", "context", "task-123"], cwd=tmp_path)

    assert output == "TASK:task-123|pending|P2|refactor|SIMPLE\n"
    env = captured["env"]
    assert isinstance(env, dict)
    assert "PYTHONPATH" not in env
    assert env["KEEP_ME"] == "1"


def test_build_claude_command_includes_schema_and_minified_agents(tmp_path):
    module = _load_module()
    schema_path = tmp_path / "schema.json"
    schema_path.write_text('{"type":"object"}')
    agents_path = tmp_path / "agents.json"
    agents_path.write_text('{\n  "reader": { "description": "Read only", "prompt": "Inspect files" }\n}\n')

    command = module._build_claude_command(
        schema_path=schema_path,
        agents_path=agents_path,
        agents_payload=None,
        model="sonnet",
        allowed_tools="Read,Agent,StructuredOutput",
        permission_mode="bypassPermissions",
    )

    assert "--json-schema" in command
    assert str(schema_path) in command
    assert "--agents" in command
    assert '{"reader":{"description":"Read only","prompt":"Inspect files"}}' in command


def test_build_prompt_from_spec_generates_direct_readonly_contract():
    module = _load_module()

    prompt = module._build_prompt_from_spec(
        {
            "objective": "State what the file does.",
            "paths": ["backend/app/services/session_ingestion/adapters/claude_code.py"],
            "response_contract": "Reply with exactly one sentence that states what the file does.",
            "constraints": ["Do not inspect any other files."],
        }
    )

    assert "Read only `backend/app/services/session_ingestion/adapters/claude_code.py`." in prompt
    assert "Objective: State what the file does." in prompt
    assert "Reply with exactly one sentence that states what the file does." in prompt
    assert "- Do not inspect any other files." in prompt


def test_build_prompt_from_spec_generates_delegated_contract():
    module = _load_module()

    prompt = module._build_prompt_from_spec(
        {
            "objective": "State what the file does.",
            "paths": ["backend/app/services/session_ingestion/adapters/claude_code.py"],
            "response_contract": "Reply with exactly one sentence that states what the file does.",
            "constraints": ["Do not add extra commentary."],
            "agent": {"name": "opus-reasoner"},
        }
    )

    assert "Use exactly one Agent subagent named `opus-reasoner`." in prompt
    assert (
        "Have the subagent read only `backend/app/services/session_ingestion/adapters/claude_code.py`."
        in prompt
    )
    assert "Reply with exactly one sentence that states what the file does." in prompt
    assert "- Do not add extra commentary." in prompt


def test_build_agents_payload_from_spec_uses_defaults_and_supported_fields():
    module = _load_module()

    payload = module._build_agents_payload_from_spec(
        {
            "agent": {
                "name": "reader",
                "tools": ["Read"],
                "model": "sonnet",
            }
        }
    )

    assert payload == {
        "reader": {
            "description": "Scoped analysis worker",
            "prompt": "Read only the requested files and report back briefly.",
            "tools": ["Read"],
            "model": "sonnet",
        }
    }


def test_allowed_tools_from_spec_defaults_to_agent_or_read():
    module = _load_module()

    assert module._allowed_tools_from_spec({"paths": ["x.py"]}) == "Read"
    assert module._allowed_tools_from_spec({"agent": {"name": "reader"}}) == "Agent"
    assert (
        module._allowed_tools_from_spec({"allowed_tools": ["Read", "StructuredOutput"]})
        == "Read,StructuredOutput"
    )


def test_parse_task_context_extracts_core_fields():
    module = _load_module()

    parsed = module._parse_task_context(
        "\n".join(
            [
                "TASK:task-123|running|P2|refactor|SIMPLE",
                "TITLE:Refactor: backend/cli/lib/autosnapshot.py",
                "DESCRIPTION:Simplify the file without regressions.",
                "DONE_WHEN[2]:Tests pass | Nesting reduced",
                "CONTEXT:modify:backend/cli/lib/autosnapshot.py",
                "WORKTREE_PATH:/tmp/task-123",
                "TASK_BRANCH:task-123/main",
            ]
        )
    )

    assert parsed == {
        "done_when": ["Tests pass", "Nesting reduced"],
        "context_entries": [{"mode": "modify", "path": "backend/cli/lib/autosnapshot.py"}],
        "task_id": "task-123",
        "task_status": "running",
        "task_type": "refactor",
        "title": "Refactor: backend/cli/lib/autosnapshot.py",
        "description": "Simplify the file without regressions.",
        "worktree_path": "/tmp/task-123",
        "task_branch": "task-123/main",
    }


def test_discover_related_tests_prefers_exact_match_and_content_match(tmp_path):
    module = _load_module()
    workdir = tmp_path
    tests_root = workdir / "backend" / "tests" / "cli"
    tests_root.mkdir(parents=True)
    (tests_root / "test_autosnapshot.py").write_text("def test_a():\n    pass\n")
    (tests_root / "test_snapshots.py").write_text(
        "from cli.lib.autosnapshot import ensure_baseline\n"
    )

    related = module._discover_related_tests(
        workdir=workdir,
        target_paths=["backend/cli/lib/autosnapshot.py"],
    )

    assert related == [
        "backend/tests/cli/test_autosnapshot.py",
        "backend/tests/cli/test_snapshots.py",
    ]


def test_build_prompt_from_task_context_generates_task_contract():
    module = _load_module()

    prompt = module._build_prompt_from_task_context(
        {
            "task_id": "task-123",
            "title": "Refactor autosnapshot",
            "description": "Simplify autosnapshot without regressions.",
            "done_when": ["Tests pass", "Nesting reduced"],
            "task_type": "refactor",
        },
        target_paths=["backend/cli/lib/autosnapshot.py"],
        related_tests=["backend/tests/cli/test_autosnapshot.py"],
        feedback_text="Second pass must reduce file size and remove banner comments.",
    )

    assert "Use exactly one Agent subagent named `task-analyst`" in prompt
    assert "`backend/cli/lib/autosnapshot.py`" in prompt
    assert "`dt pytest backend/tests/cli/test_autosnapshot.py`" in prompt
    assert "Prefer helper extraction, reduced nesting, and removal of duplicate logic" in prompt
    assert "Second pass must reduce file size and remove banner comments." in prompt


def test_ensure_session_metadata_sets_external_id_on_create(tmp_path):
    module = _load_module()
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: None)
    upsert_session = AsyncMock()

    class FakeSession:
        id = object()

    class SessionUpsertRequest:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Select:
        def where(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

    class _AsyncSessionCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.dict(
        sys.modules,
        {
            "sqlalchemy": types.SimpleNamespace(select=lambda *_args, **_kwargs: _Select()),
            "app.db": types.SimpleNamespace(async_session=lambda: _AsyncSessionCtx()),
            "app.models": types.SimpleNamespace(Session=FakeSession),
            "app.services.session_ingestion.models": types.SimpleNamespace(
                SessionUpsertRequest=SessionUpsertRequest
            ),
            "app.services.session_ingestion.service": types.SimpleNamespace(
                upsert_session=upsert_session
            ),
        },
    ):
        asyncio.run(
            module._ensure_session_metadata(
                session_id="session-1",
                project_id="agent-hub",
                transcript_path=tmp_path / "session.jsonl",
                workdir=tmp_path,
                external_id="task-123",
            )
        )

    request = upsert_session.await_args.args[1]
    assert request.external_id == "task-123"


def test_ensure_session_metadata_backfills_external_id_on_existing_session(tmp_path):
    module = _load_module()
    existing = SimpleNamespace(provider_metadata={}, external_id=None)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalar_one_or_none=lambda: existing)

    class FakeSession:
        id = object()

    class _Select:
        def where(self, *_args, **_kwargs):
            return self

        def limit(self, *_args, **_kwargs):
            return self

    class _AsyncSessionCtx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, exc_type, exc, tb):
            return False

    with patch.dict(
        sys.modules,
        {
            "sqlalchemy": types.SimpleNamespace(select=lambda *_args, **_kwargs: _Select()),
            "app.db": types.SimpleNamespace(async_session=lambda: _AsyncSessionCtx()),
            "app.models": types.SimpleNamespace(Session=FakeSession),
            "app.services.session_ingestion.models": types.SimpleNamespace(
                SessionUpsertRequest=object
            ),
            "app.services.session_ingestion.service": types.SimpleNamespace(
                upsert_session=AsyncMock()
            ),
        },
    ):
        asyncio.run(
            module._ensure_session_metadata(
                session_id="session-1",
                project_id="agent-hub",
                transcript_path=tmp_path / "session.jsonl",
                workdir=tmp_path,
                external_id="task-123",
            )
        )

    assert existing.external_id == "task-123"
    assert existing.provider_metadata["transcript_path"] == str(tmp_path / "session.jsonl")
    assert existing.provider_metadata["repo_root"] == str(tmp_path.resolve())
    db.commit.assert_awaited_once()


def test_sync_session_metadata_if_needed_tracks_session_and_transcript_markers(tmp_path):
    module = _load_module()

    with patch.object(module, "_ensure_session_metadata", new_callable=AsyncMock) as ensure:
        state = {"session_id": "session-1"}

        assert (
            module._sync_session_metadata_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is True
        )
        ensure.assert_awaited_once()
        first_call = ensure.await_args
        assert first_call.kwargs["transcript_path"] is None
        assert first_call.kwargs["external_id"] == "task-123"

        assert (
            module._sync_session_metadata_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is False
        )
        assert ensure.await_count == 1

        state["transcript_path"] = str(tmp_path / "session.jsonl")
        assert (
            module._sync_session_metadata_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is True
        )
        assert ensure.await_count == 2
        second_call = ensure.await_args
        assert second_call.kwargs["transcript_path"] == tmp_path / "session.jsonl"


def test_sync_transcript_events_if_needed_tracks_line_count_and_checkpoint(tmp_path):
    module = _load_module()

    with patch.object(module, "_ingest_transcript", new_callable=AsyncMock) as ingest:
        ingest.side_effect = [
            {"next_checkpoint": "4", "events_appended": 3, "events_skipped": 0, "last_turn": 1, "last_sequence": 3},
            {"next_checkpoint": "7", "events_appended": 2, "events_skipped": 0, "last_turn": 1, "last_sequence": 5},
        ]
        state = {
            "session_id": "session-1",
            "transcript_path": str(tmp_path / "session.jsonl"),
            "transcript_progress": {"line_count": 10},
        }

        assert (
            module._sync_transcript_events_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is True
        )
        assert state["live_ingest_checkpoint"] == "4"
        first_call = ingest.await_args
        assert first_call.kwargs["checkpoint"] is None

        assert (
            module._sync_transcript_events_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is False
        )
        assert ingest.await_count == 1

        state["transcript_progress"] = {"line_count": 12}
        assert (
            module._sync_transcript_events_if_needed(
                state=state,
                workdir=tmp_path,
                project_id="agent-hub",
                external_id="task-123",
            )
            is True
        )
        assert ingest.await_count == 2
        second_call = ingest.await_args
        assert second_call.kwargs["checkpoint"] == "4"
        assert state["live_ingest_checkpoint"] == "7"


def test_read_transcript_progress_extracts_last_entry_metadata(tmp_path):
    module = _load_module()
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"type":"assistant","message":{"model":"claude-sonnet-4-6","role":"assistant","content":[{"type":"text","text":"Starting"}]}}',
                '{"type":"progress","data":{"type":"agent_progress","agentId":"agent-1","message":{"type":"assistant","message":{"model":"claude-opus-4-6","role":"assistant","content":[{"type":"text","text":"Done"}]}}}}',
            ]
        )
        + "\n"
    )

    progress = module._read_transcript_progress(str(transcript))

    assert progress == {
        "line_count": 2,
        "size_bytes": transcript.stat().st_size,
        "last_type": "progress",
        "last_model": "claude-opus-4-6",
        "last_agent_id": "agent-1",
        "last_nested_type": "assistant",
    }


def test_build_live_summary_includes_transcript_progress():
    module = _load_module()

    summary = module._build_live_summary(
        command=["claude", "--print"],
        artifact_dir=Path("/tmp/artifacts"),
        stdout_path=Path("/tmp/artifacts/stdout.jsonl"),
        stderr_path=Path("/tmp/artifacts/stderr.log"),
        metadata_path=Path("/tmp/artifacts/run.json"),
        state={
            "status": "running",
            "transcript_progress": {"line_count": 3, "last_type": "progress"},
            "last_progress_at": "2026-03-26T12:00:00+00:00",
        },
    )

    assert summary["transcript_progress"] == {"line_count": 3, "last_type": "progress"}
    assert summary["last_progress_at"] == "2026-03-26T12:00:00+00:00"
