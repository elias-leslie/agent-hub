from __future__ import annotations

import importlib.util
from pathlib import Path

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
