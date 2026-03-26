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
        model="sonnet",
        allowed_tools="Read,Agent,StructuredOutput",
        permission_mode="bypassPermissions",
    )

    assert "--json-schema" in command
    assert str(schema_path) in command
    assert "--agents" in command
    assert '{"reader":{"description":"Read only","prompt":"Inspect files"}}' in command


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
