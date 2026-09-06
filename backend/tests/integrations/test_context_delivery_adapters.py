from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import stat
import sys
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
CLIENT = REPO_ROOT / "integrations/context-delivery/bin/agent-hub-context-client"
CLAUDE_LAUNCHER = REPO_ROOT / "integrations/context-delivery/claude/launcher"
CODEX_LAUNCHER = REPO_ROOT.parent / "codex-config/bin/codex"


@pytest.fixture(autouse=True)
def _isolate_aico_launcher_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("AICO_SESSION_ID", "AICO_PROJECT_ID", "AICO_WIDGET_ID"):
        monkeypatch.delenv(name, raising=False)


async def _run(
    *argv: str,
    env: dict[str, str] | None = None,
    stdin: str | None = None,
) -> tuple[int, str, str]:
    process = await asyncio.create_subprocess_exec(
        *argv,
        env=env,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate(stdin.encode() if stdin is not None else None)
    return process.returncode or 0, stdout.decode(), stderr.decode()


def _executable(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def fake_context_cli(tmp_path: Path) -> Path:
    return _executable(
        tmp_path / "agent-hub-context",
        """#!/usr/bin/env python3
import hashlib
import json
import os
import sys
import tomllib
import time

args = sys.argv[1:]
def value(flag, default=None):
    try:
        return args[args.index(flag) + 1]
    except (ValueError, IndexError):
        return default

if os.environ.get("FAKE_ARGV_LOG"):
    with open(os.environ["FAKE_ARGV_LOG"], "w", encoding="utf-8") as handle:
        json.dump(args, handle)

status = os.environ.get("FAKE_STATUS", "ok")
rendered = os.environ.get("FAKE_RENDERED", "canonical context")
if os.environ.get("FAKE_SLEEP"):
    time.sleep(float(os.environ["FAKE_SLEEP"]))
digest = hashlib.sha256(rendered.encode()).hexdigest()
if os.environ.get("FAKE_BAD_HASH"):
    digest = "0" * 64
artifact_id = "context-" + digest
if os.environ.get("FAKE_BAD_ARTIFACT"):
    artifact_id = "context-wrong"
required = []
delivered = []
missing = []
if os.environ.get("FAKE_BAD_POLICY"):
    required = ["must-deliver"]
response = {
    "schema_version": "agent-hub.context.v1",
    "context_version": os.environ.get("FAKE_CONTEXT_VERSION", "1"),
    "delivery_id": "delivery-1",
    "artifact_id": artifact_id,
    "generated_at": "2026-07-16T00:00:00Z",
    "status": status,
    "delivery_mode": "additive",
    "recommended_role": "developer",
    "native_context_policy": "preserve",
    "precedence": "preserve native harness messages; add operator context without replacement",
    "payload_hash_algorithm": "sha256",
    "payload_hash": digest,
    "metadata": {
        "consumer_surface": os.environ.get("FAKE_CONSUMER_SURFACE", value("--surface", "unknown")),
        "consumer_profile": value("--profile", "agent_startup"),
        "capabilities": [],
        "project_id": os.environ.get("FAKE_PROJECT_ID", value("--project")),
        "session_id": value("--session"),
        "query": value("--query", "startup context"),
        "query_hash": "query",
        "client_metadata": {},
    },
    "blocks": [],
    "rendered": rendered,
    "estimated_tokens": 4,
    "required_policy": {
        "state": "complete" if status == "ok" else "failed",
        "required_source_ids": required,
        "delivered_source_ids": delivered,
        "missing_source_ids": missing,
        "pending_review_source_ids": [],
    },
    "failure": None if status == "ok" else {
        "operation": "test", "error_type": "TestFailure", "error_message": "failed"
    },
}
print(json.dumps(response))
raise SystemExit(0 if status == "ok" else 2)
""",
    )


@pytest.mark.asyncio
async def test_client_persists_distinct_immutable_artifacts(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    env = {**os.environ, "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli)}
    command = (
        str(CLIENT),
        "deliver",
        "--surface",
        "pi",
        "--cwd",
        str(REPO_ROOT),
        "--session",
        "session-1",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "descriptor",
    )
    first_code, first_stdout, _ = await _run(*command, env=env)
    second_code, second_stdout, _ = await _run(*command, env=env)

    assert first_code == second_code == 0
    first = json.loads(first_stdout)
    second = json.loads(second_stdout)
    assert first["payload_hash"] == hashlib.sha256(b"canonical context").hexdigest()
    assert first["contract_path"] != second["contract_path"]
    assert first["text_path"] != second["text_path"]
    assert Path(first["contract_path"]).read_text().endswith("\n")
    assert Path(first["text_path"]).read_text() == "canonical context"


@pytest.mark.asyncio
async def test_client_does_not_trim_large_canonical_delivery(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    rendered = "BEGIN\n" + ("context-line\n" * 6000) + "END"
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_RENDERED": rendered,
    }
    code, stdout, stderr = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "claude_code",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "text",
        env=env,
    )

    assert code == 0, stderr
    assert stdout == rendered
    artifact = next((tmp_path / "artifacts").rglob("*.md"))
    assert artifact.read_text() == rendered


@pytest.mark.asyncio
async def test_client_uses_backend_registry_project_for_artifact_path(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    argv_log = tmp_path / "argv.json"
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_ARGV_LOG": str(argv_log),
        "FAKE_PROJECT_ID": "registry-project",
    }
    code, stdout, stderr = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "pi",
        "--cwd",
        str(REPO_ROOT),
        "--repo-root",
        str(REPO_ROOT),
        "--session",
        "session-1",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "descriptor",
        env=env,
    )

    assert code == 0, stderr
    invoked = json.loads(argv_log.read_text())
    assert "--project" not in invoked
    descriptor = json.loads(stdout)
    assert Path(descriptor["contract_path"]).parent == (
        tmp_path / "artifacts/pi/registry-project/session-1"
    )


@pytest.mark.asyncio
async def test_generic_hook_maps_native_metadata_and_emits_additive_context(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    argv_log = tmp_path / "argv.json"
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_ARGV_LOG": str(argv_log),
    }
    payload = {
        "hook_event_name": "SubagentStart",
        "session_id": "codex-session",
        "cwd": str(REPO_ROOT),
        "agent_id": "agent-7",
        "agent_type": "explorer",
        "turn_id": "turn-9",
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "claude_code",
        "--agent-slug",
        "operator-codex",
        "--consumer-tag",
        "operator",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(payload),
    )

    assert code == 0
    output = json.loads(stdout)
    assert output["hookSpecificOutput"] == {
        "hookEventName": "SubagentStart",
        "additionalContext": "canonical context",
    }
    invoked = json.loads(argv_log.read_text())
    assert invoked[invoked.index("--session") + 1] == "codex-session"
    assert invoked[invoked.index("--hook-event") + 1] == "SubagentStart"
    assert invoked[invoked.index("--subagent-id") + 1] == "agent-7"
    assert invoked[invoked.index("--subagent-type") + 1] == "explorer"
    assert invoked[invoked.index("--agent-slug") + 1] == "operator-codex"
    assert invoked[invoked.index("--consumer-tag") + 1] == "operator"


@pytest.mark.asyncio
async def test_aico_hook_uses_durable_session_without_trusting_project_hint(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    argv_log = tmp_path / "argv.json"
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_ARGV_LOG": str(argv_log),
        "AICO_SESSION_ID": "aico-durable-session",
        "AICO_PROJECT_ID": "noncanonical-project-hint",
        "AICO_WIDGET_ID": "widget-7",
    }
    code, _stdout, stderr = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "claude_code",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "native-claude-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )

    assert code == 0, stderr
    invoked = json.loads(argv_log.read_text())
    assert invoked[invoked.index("--session") + 1] == "aico-durable-session"
    assert "--project" not in invoked
    metadata = {
        value.split("=", 1)[0]: value.split("=", 1)[1]
        for index, value in enumerate(invoked)
        if index > 0 and invoked[index - 1] == "--metadata"
    }
    assert metadata["native_session_id"] == "native-claude-session"
    assert metadata["aico_session_id"] == "aico-durable-session"
    assert metadata["aico_project_hint"] == "noncanonical-project-hint"
    assert metadata["aico_widget_id"] == "widget-7"


@pytest.mark.asyncio
async def test_codex_hook_emits_lossless_native_developer_context_json(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    env = {**os.environ, "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli)}
    code, stdout, stderr = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "codex",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "codex-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )

    assert code == 0, stderr
    assert json.loads(stdout)["hookSpecificOutput"] == {
        "hookEventName": "SessionStart",
        "additionalContext": "canonical context",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["codex", "claude_code"])
async def test_session_start_failure_warns_without_blocking_or_injecting(
    tmp_path: Path, fake_context_cli: Path, surface: str
) -> None:
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_STATUS": "failed",
        "FAKE_RENDERED": "required context unavailable",
    }
    code, stdout, stderr = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        surface,
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "codex-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )

    output = json.loads(stdout)
    assert code == 0, stderr
    assert "continue" not in output
    assert "stopReason" not in output
    assert "additionalContext" not in output["hookSpecificOutput"]
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert "continuing with native model context only" in output["systemMessage"]


@pytest.mark.asyncio
async def test_codex_binding_records_real_native_session_without_reinjecting(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    artifact_root = tmp_path / "artifacts"
    base_env = {**os.environ, "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli)}
    delivery_code, delivery_stdout, delivery_stderr = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "codex",
        "--artifact-root",
        str(artifact_root),
        "--emit",
        "descriptor",
        env=base_env,
    )
    assert delivery_code == 0, delivery_stderr
    descriptor = json.loads(delivery_stdout)
    env = {
        **base_env,
        "AGENT_HUB_CONTEXT_PREINJECTED_HASH": descriptor["payload_hash"],
        "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT": descriptor["contract_path"],
        "AGENT_HUB_CONTEXT_PREINJECTED_TEXT": descriptor["text_path"],
    }
    bind_code, bind_stdout, bind_stderr = await _run(
        str(CLIENT),
        "bind",
        "--surface",
        "codex",
        "--artifact-root",
        str(artifact_root),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "real-codex-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )

    assert bind_code == 0, bind_stderr
    assert json.loads(bind_stdout) == {}
    binding_paths = list(artifact_root.rglob("bindings/*.json"))
    assert len(binding_paths) == 1
    binding = json.loads(binding_paths[0].read_text())
    assert binding["native_session_id"] == "real-codex-session"
    assert binding["payload_hash"] == descriptor["payload_hash"]
    assert binding["contract_path"] == descriptor["contract_path"]


@pytest.mark.asyncio
async def test_codex_binding_warns_but_does_not_block_direct_binary_without_context(
    tmp_path: Path,
) -> None:
    env = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith("AGENT_HUB_CONTEXT_PREINJECTED_")
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "bind",
        "--surface",
        "codex",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "session_id": "bypassed-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )

    output = json.loads(stdout)
    assert code == 0
    assert "continue" not in output
    assert "stopReason" not in output
    assert "additionalContext" not in output["hookSpecificOutput"]
    assert "continuing with native model context only" in output["systemMessage"]


@pytest.mark.asyncio
async def test_invalid_contract_fails_closed_with_a_persisted_notice(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_BAD_HASH": "1",
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "claude_code",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "descriptor",
        env=env,
    )

    descriptor = json.loads(stdout)
    assert code == 2
    assert descriptor["status"] == "failed"
    assert "could not deliver or validate" in Path(descriptor["text_path"]).read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("FAKE_CONTEXT_VERSION", "stale"),
        ("FAKE_CONSUMER_SURFACE", "codex"),
        ("FAKE_BAD_ARTIFACT", "1"),
        ("FAKE_BAD_POLICY", "1"),
    ),
)
async def test_client_rejects_stale_wrong_surface_or_incoherent_contracts(
    tmp_path: Path,
    fake_context_cli: Path,
    field: str,
    value: str,
) -> None:
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        field: value,
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "claude_code",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "descriptor",
        env=env,
    )

    descriptor = json.loads(stdout)
    assert code == 2
    assert descriptor["status"] == "failed"


@pytest.mark.asyncio
async def test_client_times_out_a_hung_canonical_cli_and_persists_failure(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "AGENT_HUB_CONTEXT_TIMEOUT_SECONDS": "0.05",
        "FAKE_SLEEP": "10",
    }
    code, stdout, stderr = await _run(
        str(CLIENT),
        "deliver",
        "--surface",
        "pi",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        "--emit",
        "descriptor",
        env=env,
    )

    descriptor = json.loads(stdout)
    assert code == 2
    assert descriptor["status"] == "failed"
    assert "exceeded 0.05s" in stderr


@pytest.mark.asyncio
async def test_gemini_before_model_preserves_native_request_on_failed_delivery(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_STATUS": "failed",
        "FAKE_RENDERED": "required context unavailable",
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "gemini",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "BeforeModel",
                "session_id": "gemini-session",
                "cwd": str(REPO_ROOT),
                "llm_request": {
                    "model": "gemini-test",
                    "messages": [{"role": "user", "content": "do work"}],
                    "config": {"systemInstruction": "NATIVE GEMINI"},
                },
            }
        ),
    )

    output = json.loads(stdout)
    assert code == 0
    assert "decision" not in output
    assert "reason" not in output
    assert "continue" not in output
    assert "llm_request" not in output["hookSpecificOutput"]
    assert "continuing with native model context only" in output["systemMessage"]


@pytest.mark.asyncio
async def test_gemini_hook_degrades_when_delivery_artifacts_cannot_be_written(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("file blocks artifact directory creation")
    env = {**os.environ, "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli)}

    code, stdout, stderr = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "gemini",
        "--artifact-root",
        str(blocked_root),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "BeforeModel",
                "session_id": "gemini-session",
                "cwd": str(REPO_ROOT),
                "llm_request": {
                    "model": "gemini-test",
                    "messages": [{"role": "user", "content": "native task"}],
                    "config": {"systemInstruction": "NATIVE GEMINI"},
                },
            }
        ),
    )

    output = json.loads(stdout)
    assert code == 0
    assert "llm_request" not in output["hookSpecificOutput"]
    assert "continue" not in output
    assert "continuing with native model context only" in output["systemMessage"]
    assert "could not persist degraded delivery evidence" in stderr


@pytest.mark.asyncio
async def test_gemini_before_model_appends_exact_bytes_without_mutating_native_system(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    rendered = "CANONICAL <tool-usage>literal tags</tool-usage>"
    argv_log = tmp_path / "argv.json"
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "FAKE_RENDERED": rendered,
        "FAKE_ARGV_LOG": str(argv_log),
    }
    original_request = {
        "model": "gemini-test",
        "messages": [{"role": "user", "content": "do work"}],
        "config": {"systemInstruction": "NATIVE GEMINI"},
    }
    code, stdout, stderr = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "gemini",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "BeforeModel",
                "session_id": "gemini-session",
                "cwd": str(REPO_ROOT),
                "llm_request": original_request,
            }
        ),
    )

    output = json.loads(stdout)
    request = output["hookSpecificOutput"]["llm_request"]
    assert code == 0, stderr
    assert request["config"] == original_request["config"]
    assert request["messages"][0] == {"role": "user", "content": rendered}
    assert request["messages"][1:] == original_request["messages"]
    assert request["messages"][-1] == {"role": "user", "content": "do work"}
    invoked = json.loads(argv_log.read_text())
    assert invoked[invoked.index("--model") + 1] == "gemini-test"


@pytest.mark.asyncio
async def test_claude_session_hook_is_not_suppressed_by_a_stale_launcher_hash(
    tmp_path: Path, fake_context_cli: Path
) -> None:
    digest = hashlib.sha256(b"canonical context").hexdigest()
    env = {
        **os.environ,
        "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
        "AGENT_HUB_CONTEXT_PREINJECTED_HASH": digest,
    }
    code, stdout, _ = await _run(
        str(CLIENT),
        "hook",
        "--surface",
        "claude_code",
        "--artifact-root",
        str(tmp_path / "artifacts"),
        env=env,
        stdin=json.dumps(
            {
                "hook_event_name": "SessionStart",
                "source": "compact",
                "session_id": "claude-session",
                "cwd": str(REPO_ROOT),
            }
        ),
    )
    assert code == 0
    assert json.loads(stdout)["hookSpecificOutput"]["additionalContext"] == (
        "canonical context"
    )


@pytest.mark.asyncio
async def test_installer_links_sources_and_detects_drift(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    fake_repo = workspace / "agent-hub"
    fake_claude = workspace / "claude-config"
    fake_codex = workspace / "codex-config"
    home = tmp_path / "home"
    shutil.copytree(REPO_ROOT / "integrations", fake_repo / "integrations")
    _executable(fake_repo / "backend/.venv/bin/agent-hub-context", "#!/bin/sh\nexit 0\n")
    (fake_claude / "hooks").mkdir(parents=True)
    claude_command = f"{home}/.local/bin/agent-hub-context-client bind --surface claude_code"
    (fake_claude / "settings.json").write_text(
        json.dumps(
            {
                "hooks": {
                    event: [
                        {
                            "matcher": "",
                            "hooks": [
                                {
                                    "type": "command",
                                    "command": claude_command,
                                    "timeout": 10,
                                }
                            ],
                        }
                    ]
                    for event in ("SessionStart", "SubagentStart")
                }
            }
        )
        + "\n"
    )
    _executable(fake_claude / "hooks/SessionStart.sh", "#!/bin/sh\nexit 0\n")
    _executable(
        fake_claude / "hooks/canonical-context-metadata.sh",
        "#!/bin/sh\ncanonical_context_metadata() { return 0; }\n",
    )
    _executable(fake_claude / "hooks/PostToolUse.sh", "#!/bin/sh\nexit 0\n")
    _executable(fake_claude / "hooks/Stop.sh", "#!/bin/sh\nexit 0\n")
    _executable(
        fake_claude / "bin/claude-gpt",
        '#!/bin/sh\nexec "$HOME/.claude/bin/claude" "$@"\n',
    )
    (fake_claude / "claude-gpt-settings.json").write_text(
        json.dumps({"model": "gpt-test", "env": {"ANTHROPIC_AUTH_TOKEN": "unused"}})
        + "\n"
    )
    (fake_codex / "bin").mkdir(parents=True)
    shutil.copy2(
        REPO_ROOT.parent / "codex-config/config.toml",
        fake_codex / "config.toml",
    )
    shutil.copy2(
        REPO_ROOT.parent / "codex-config/hooks.json",
        fake_codex / "hooks.json",
    )
    shutil.copy2(
        REPO_ROOT.parent / "codex-config/bin/codex",
        fake_codex / "bin/codex",
    )
    (home / ".gemini").mkdir(parents=True)
    old_gemini = {
        "hooks": {
            "SessionStart": [
                {"command": "/old/aico-mandates-gemini.sh", "timeout": 5000}
            ],
            "BeforeAgent": [
                {
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"{home}/.local/bin/agent-hub-context-client hook --surface gemini",
                            "timeout": 60000,
                        }
                    ],
                    "sequential": True,
                }
            ],
        }
    }
    (home / ".gemini/settings.json").write_text(json.dumps(old_gemini))
    (home / ".codex/bin").mkdir(parents=True)
    _executable(home / ".codex/bin/codex", "#!/bin/sh\n# old mutable wrapper\n")
    (home / ".codex/config.toml").write_text("# old home config\n")
    (home / ".codex/generated").mkdir(parents=True)
    (home / ".codex/generated/agent-hub-session-start.md").write_text("stale")
    (home / ".codex/hooks").mkdir(parents=True)
    _executable(home / ".codex/hooks/session-start.sh", "#!/bin/sh\nexit 0\n")
    (home / ".claude").mkdir(parents=True)
    (home / ".claude/CLAUDE.md").write_text("stale parallel policy")

    surfaces = [
        "--surface",
        "claude_code",
        "--surface",
        "codex",
        "--surface",
        "gemini",
        "--surface",
        "pi",
    ]
    code, stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        *surfaces,
    )
    assert code == 0, stdout
    assert (home / ".claude/bin/claude").is_symlink()
    assert (home / ".local/bin/claude-gpt").is_symlink()
    assert (home / ".claude/claude-gpt-settings.json").is_symlink()
    assert (home / ".codex/bin/codex").is_symlink()
    assert (home / ".codex/config.toml").is_symlink()
    assert (home / ".codex/hooks.json").resolve() == fake_codex / "hooks.json"
    assert not (home / ".codex/generated/agent-hub-session-start.md").exists()
    assert not (home / ".codex/hooks/session-start.sh").exists()
    assert not (home / ".claude/CLAUDE.md").exists()
    assert (home / ".pi/agent/extensions/agent-hub.ts").is_symlink()
    claude_settings = json.loads((fake_claude / "settings.json").read_text())
    assert "SubagentStart" in claude_settings["hooks"]
    gemini_settings = json.loads((home / ".gemini/settings.json").read_text())
    assert "BeforeModel" in gemini_settings["hooks"]
    assert not gemini_settings["hooks"].get("BeforeAgent")
    assert "aico-mandates-gemini.sh" not in json.dumps(gemini_settings)
    install_result = json.loads(stdout)
    gemini_result = next(
        result
        for result in install_result["results"]
        if result["target"] == str(home / ".gemini/settings.json")
    )
    gemini_backup = Path(gemini_result["backup"])
    assert json.loads(gemini_backup.read_text()) == old_gemini
    assert stat.S_IMODE(gemini_backup.stat().st_mode) == stat.S_IRUSR
    backups_after_change = set(
        (home / ".local/state/agent-hub/adapter-backups").iterdir()
    )

    repeat_code, repeat_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        *surfaces,
    )
    assert repeat_code == 0, repeat_stdout
    assert set((home / ".local/state/agent-hub/adapter-backups").iterdir()) == (
        backups_after_change
    )

    check_code, check_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        *surfaces,
        "--check",
    )
    assert check_code == 0, check_stdout
    assert json.loads(check_stdout)["passed"] is True

    gemini_settings = json.loads((home / ".gemini/settings.json").read_text())
    gemini_settings["hooks"]["BeforeModel"][-1]["hooks"][0]["timeout"] = 1
    (home / ".gemini/settings.json").write_text(json.dumps(gemini_settings))
    shape_code, shape_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        "--surface",
        "gemini",
        "--check",
    )
    assert shape_code == 1
    assert json.loads(shape_stdout)["passed"] is False

    repair_code, repair_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        "--surface",
        "gemini",
    )
    assert repair_code == 0, repair_stdout
    gemini_settings = json.loads((home / ".gemini/settings.json").read_text())
    gemini_settings["hooks"]["BeforeModel"].append(
        gemini_settings["hooks"]["BeforeModel"][-1]
    )
    (home / ".gemini/settings.json").write_text(json.dumps(gemini_settings))
    duplicate_code, duplicate_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        "--surface",
        "gemini",
        "--check",
    )
    assert duplicate_code == 1
    assert json.loads(duplicate_stdout)["passed"] is False

    (home / ".pi/agent/extensions/agent-hub.ts").unlink()
    (home / ".pi/agent/extensions/agent-hub.ts").write_text("drift")
    drift_code, drift_stdout, _ = await _run(
        sys.executable,
        str(fake_repo / "integrations/context-delivery/install.py"),
        "--repo-root",
        str(fake_repo),
        "--home",
        str(home),
        "--surface",
        "pi",
        "--check",
    )
    assert drift_code == 1
    assert json.loads(drift_stdout)["passed"] is False


def test_codex_sources_preserve_native_prompt_and_use_canonical_hooks() -> None:
    codex_root = REPO_ROOT.parent / "codex-config"
    wrapper = (codex_root / "bin/codex").read_text()
    wrapper_commands = "\n".join(
        line for line in wrapper.splitlines() if not line.lstrip().startswith("#")
    )
    config = (codex_root / "config.toml").read_text()

    assert "model_instructions_file" not in wrapper_commands
    assert "runtime-context-startup.sh" not in wrapper_commands
    assert '"deliver",' in wrapper
    assert '"--surface",' in wrapper
    assert '"codex",' in wrapper
    assert 'setting = f"developer_instructions=' in wrapper
    assert 'if descriptor["status"] != "ok"' in wrapper
    assert "timeout=20" in wrapper
    assert "except subprocess.TimeoutExpired" in wrapper
    assert set(tomllib.loads(config)["hooks"]) == {"state"}
    hooks = json.loads((codex_root / "hooks.json").read_text())["hooks"]
    for event in ("SessionStart", "SubagentStart"):
        assert len(hooks[event]) == 1
        assert hooks[event][0]["hooks"][0]["command"] == (
            "/home/kasadis/.local/bin/agent-hub-context-client bind --surface codex"
        )


def test_pi_source_degrades_to_native_prompt_without_consuming_input() -> None:
    extension = (
        REPO_ROOT / "integrations/context-delivery/pi/agent-hub.ts"
    ).read_text()

    assert 'return { action: "handled" }' not in extension
    assert 'return { action: "continue" }' in extension
    assert "AH: DEGRADED" in extension
    assert "continuing with native context only" in extension
    assert "return { systemPrompt: event.systemPrompt }" in extension
    assert "stop-work notice" not in extension


def test_claude_sources_do_not_add_parallel_model_context() -> None:
    claude_root = REPO_ROOT.parent / "claude-config"
    summitflow_root = REPO_ROOT.parent / "summitflow"
    session_start = (claude_root / "hooks/SessionStart.sh").read_text()
    post_tool_use = (claude_root / "hooks/PostToolUse.sh").read_text()
    stop = (claude_root / "hooks/Stop.sh").read_text()

    assert "session-start-overlay" not in session_start
    assert "project.identity.json" not in session_start
    assert "additionalContext" not in post_tool_use
    assert "CLAUDE_MESSAGES" not in post_tool_use
    assert "basename \"$GIT_ROOT\"" not in post_tool_use
    assert "basename \"$PROJECT_DIR\"" not in stop
    assert "canonical_context_metadata" in session_start
    assert "canonical_context_metadata" in post_tool_use
    assert "canonical_context_metadata" in stop
    assert not (REPO_ROOT / "CLAUDE.md").exists()
    assert not (summitflow_root / "CLAUDE.md").exists()
    assert not (claude_root / "CLAUDE.md").exists()
    assert not (claude_root / "templates/project-bootstrap/CLAUDE.md.template").exists()


def test_claude_gpt_is_a_source_owned_transport_only_wrapper() -> None:
    claude_root = REPO_ROOT.parent / "claude-config"
    wrapper = (claude_root / "bin/claude-gpt").read_text()
    settings = json.loads((claude_root / "claude-gpt-settings.json").read_text())

    assert 'canonical_claude="${HOME}/.claude/bin/claude"' in wrapper
    assert "jq -s '.[0] * .[1]'" in wrapper
    assert "--setting-sources project,local" in wrapper
    assert '--settings "$merged_settings_file"' in wrapper
    assert "AGENT_HUB_CONTEXT_PROVIDER=openai" in wrapper
    assert "AGENT_HUB_CONTEXT_TRANSPORT_VARIANT=claude-gpt" in wrapper
    assert 'AGENT_HUB_CONTEXT_MODEL="$context_model"' in wrapper
    assert "agent-hub-context-client" not in wrapper
    assert "CLAUDE.md" not in wrapper
    assert "system-prompt" not in wrapper
    assert "hooks" not in settings
    assert settings["env"]["ANTHROPIC_AUTH_TOKEN"] == "unused"


def _hook_request_body(log_path: Path, endpoint: str) -> dict[str, object]:
    for raw in log_path.read_text().splitlines():
        argv = json.loads(raw)
        if argv and argv[-1].endswith(endpoint):
            return json.loads(argv[argv.index("-d") + 1])
    raise AssertionError(f"hook did not call {endpoint}")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider", "transport_variant", "contract_model"),
    [
        ("anthropic", None, "claude-normal-test"),
        ("openai", "claude-gpt", "gpt-transport-test"),
    ],
)
async def test_claude_lifecycle_metadata_matches_normal_and_gpt_transport(
    tmp_path: Path,
    provider: str,
    transport_variant: str | None,
    contract_model: str,
) -> None:
    claude_root = REPO_ROOT.parent / "claude-config"
    home = tmp_path / "home"
    hooks_dir = home / ".claude/hooks"
    hooks_dir.mkdir(parents=True)
    (home / ".claude/settings.json").write_text(
        json.dumps({"model": "conflicting-settings-model"})
    )
    (home / ".env.local").write_text("SUMMITFLOW_CLIENT_ID=test-client\n")

    canonical = tmp_path / "canonical.md"
    canonical.write_text("canonical hook metadata")
    digest = hashlib.sha256(canonical.read_bytes()).hexdigest()
    contract = tmp_path / "contract.json"
    contract.write_text(
        json.dumps(
            {
                "schema_version": "agent-hub.context.v1",
                "status": "ok",
                "native_context_policy": "preserve",
                "payload_hash": digest,
                "metadata": {
                    "consumer_surface": "claude_code",
                    "project_id": "agent-hub",
                    "repo_root": str(tmp_path / "project"),
                    "current_branch": "main",
                    "task": "task-audit",
                    "provider": provider,
                    "model": contract_model,
                    "client_metadata": (
                        {"transport_variant": transport_variant}
                        if transport_variant
                        else {}
                    ),
                },
            }
        )
    )

    fake_bin = tmp_path / "bin"
    curl_log = tmp_path / "curl.jsonl"
    _executable(
        fake_bin / "curl",
        f"""#!/usr/bin/env python3
import json, sys
with open({str(curl_log)!r}, "a", encoding="utf-8") as handle:
    handle.write(json.dumps(sys.argv[1:]) + "\\n")
""",
    )
    _executable(
        fake_bin / "git",
        """#!/bin/sh
case "$*" in
  *"rev-parse --verify"*) exit 1 ;;
esac
exit 0
""",
    )

    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:/usr/bin:/bin",
        "CLAUDE_CANONICAL_METADATA_HELPER": str(
            claude_root / "hooks/canonical-context-metadata.sh"
        ),
        "AGENT_HUB_CONTEXT_PREINJECTED_HASH": digest,
        "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT": str(contract),
        "AGENT_HUB_CONTEXT_PREINJECTED_TEXT": str(canonical),
        # The verified contract must win over every conflicting fallback.
        "AGENT_HUB_CONTEXT_PROVIDER": "conflicting-provider",
        "AGENT_HUB_CONTEXT_TRANSPORT_VARIANT": "conflicting-variant",
        "AGENT_HUB_CONTEXT_MODEL": "conflicting-agent-hub-model",
        "CLAUDE_MODEL": "conflicting-claude-model",
        "ANTHROPIC_MODEL": "conflicting-anthropic-model",
    }

    hook_input = json.dumps(
        {
            "cwd": str(tmp_path / "project"),
            "session_id": "session-audit",
        }
    )
    for hook_name in ("SessionStart.sh", "Stop.sh"):
        curl_log.write_text("")
        code, _stdout, stderr = await _run(
            str(claude_root / "hooks" / hook_name),
            env=environment,
            stdin=hook_input,
        )
        assert code == 0, stderr
        body = _hook_request_body(
            curl_log, "/session-ingestion/sessions/upsert"
        )
        assert body["provider"] == provider
        assert body["model"] == contract_model
        assert body["session_type"] == "claude_code"
        metadata = body["provider_metadata"]
        assert isinstance(metadata, dict)
        assert metadata["harness"] == "claude_code"
        assert metadata["repo_root"] == str(tmp_path / "project")
        if transport_variant:
            assert metadata["transport_variant"] == transport_variant
        else:
            assert "transport_variant" not in metadata


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("arguments", "setting_index", "expected_phase", "expected_session"),
    [
        (("exec", "prompt"), 1, "startup", None),
        (("e", "prompt"), 1, "startup", None),
        (("review", "--uncommitted"), 1, "startup", None),
        (("interactive prompt",), 0, "startup", None),
    ],
)
async def test_codex_launcher_places_developer_context_in_consuming_parser(
    tmp_path: Path,
    arguments: tuple[str, ...],
    setting_index: int,
    expected_phase: str,
    expected_session: str | None,
) -> None:
    canonical = tmp_path / "canonical.md"
    canonical.write_text("CODEX CANONICAL EXACT")
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    real_log = tmp_path / "real.json"
    client_log = tmp_path / "client.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
import hashlib, json, sys
payload = {canonical.read_text()!r}
with open({str(client_log)!r}, "w", encoding="utf-8") as handle:
    json.dump(sys.argv[1:], handle)
print(json.dumps({{
  "status": "ok",
  "payload_hash": hashlib.sha256(payload.encode()).hexdigest(),
  "contract_path": {str(contract)!r},
  "text_path": {str(canonical)!r}
}}))
""",
    )
    fake_real = _executable(
        tmp_path / "codex-real",
        f"""#!/usr/bin/env python3
import json, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump(sys.argv[1:], handle)
""",
    )

    code, _stdout, stderr = await _run(
        str(CODEX_LAUNCHER),
        *arguments,
        env={
            **os.environ,
            "CODEX_REAL": str(fake_real),
            "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
        },
    )

    assert code == 0, stderr
    launched = json.loads(real_log.read_text())
    assert launched[setting_index] == "-c"
    assert launched[setting_index + 1].startswith("developer_instructions=")
    assert "CODEX CANONICAL EXACT" in launched[setting_index + 1]
    if setting_index == 1:
        assert launched[0] == arguments[0]
    client_arguments = json.loads(client_log.read_text())
    assert client_arguments[client_arguments.index("--phase") + 1] == expected_phase
    if expected_session is None:
        assert "--session" not in client_arguments
    else:
        assert client_arguments[client_arguments.index("--session") + 1] == expected_session


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "arguments",
    [
        ("resume", "session-id", "native resume prompt"),
        (
            "exec",
            "-c",
            'sandbox_mode="read-only"',
            "resume",
            "session-id",
            "native exec resume prompt",
        ),
        ("fork", "session-id", "native fork prompt"),
    ],
)
async def test_codex_launcher_does_not_claim_fresh_context_on_saved_thread(
    tmp_path: Path,
    arguments: tuple[str, ...],
) -> None:
    client_log = tmp_path / "client-called"
    real_log = tmp_path / "real.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
from pathlib import Path
Path({str(client_log)!r}).write_text("called")
raise SystemExit(99)
""",
    )
    fake_real = _executable(
        tmp_path / "codex-real",
        f"""#!/usr/bin/env python3
import json, os, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump({{
      "argv": sys.argv[1:],
      "hash": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH"),
      "contract": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"),
      "text": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_TEXT"),
    }}, handle)
""",
    )

    code, _stdout, stderr = await _run(
        str(CODEX_LAUNCHER),
        *arguments,
        env={
            **os.environ,
            "CODEX_REAL": str(fake_real),
            "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
            "AGENT_HUB_CONTEXT_PREINJECTED_HASH": "stale",
            "AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT": "stale",
            "AGENT_HUB_CONTEXT_PREINJECTED_TEXT": "stale",
        },
    )

    assert code == 0
    phase = "fork" if arguments[0] == "fork" else "resume"
    assert f"continuing native {phase} without a fresh Agent Hub payload" in stderr
    assert not client_log.exists()
    launched = json.loads(real_log.read_text())
    assert launched["argv"] == list(arguments)
    assert launched["hash"] is None
    assert launched["contract"] is None
    assert launched["text"] is None


@pytest.mark.asyncio
async def test_codex_launcher_preserves_native_launch_on_failed_context(
    tmp_path: Path,
) -> None:
    failure = tmp_path / "failure.md"
    failure.write_text("<agent-hub-context-failure>unavailable</agent-hub-context-failure>")
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    real_log = tmp_path / "real.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
import json
print(json.dumps({{
  "status": "failed",
  "payload_hash": "failed",
  "contract_path": {str(contract)!r},
  "text_path": {str(failure)!r}
}}))
raise SystemExit(2)
""",
    )
    fake_real = _executable(
        tmp_path / "codex-real",
        f"""#!/usr/bin/env python3
import json, os, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump({{
      "argv": sys.argv[1:],
      "hash": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH"),
      "contract": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"),
      "text": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_TEXT"),
    }}, handle)
""",
    )
    native_argv = [
        "exec",
        "-c",
        'developer_instructions="USER NATIVE"',
        "native prompt still runs",
    ]

    code, _stdout, stderr = await _run(
        str(CODEX_LAUNCHER),
        *native_argv,
        env={
            **os.environ,
            "CODEX_REAL": str(fake_real),
            "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
        },
    )

    assert code == 0
    assert "continuing with native Codex context only" in stderr
    launched = json.loads(real_log.read_text())
    assert launched["argv"] == native_argv
    assert launched["hash"] is None
    assert launched["contract"] is None
    assert launched["text"] is None


@pytest.mark.asyncio
async def test_claude_launcher_uses_lossless_additive_directory_and_preserves_user_prompts(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical.md"
    canonical.write_text("AGENT HUB <tool-usage>EXACT</tool-usage>")
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    real_log = tmp_path / "real.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
import hashlib, json
payload = {canonical.read_text()!r}
print(json.dumps({{
  "schema_version": "agent-hub.context.v1",
  "status": "ok",
  "payload_hash": hashlib.sha256(payload.encode()).hexdigest(),
  "delivery_id": "d",
  "artifact_id": "context-" + hashlib.sha256(payload.encode()).hexdigest(),
  "contract_path": {str(contract)!r},
  "text_path": {str(canonical)!r}
}}))
""",
    )
    fake_real = _executable(
        tmp_path / "claude-real",
        f"""#!/usr/bin/env python3
import json, os, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump({{
      "argv": sys.argv[1:],
      "hash": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH"),
      "contract": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"),
      "text": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_TEXT"),
      "additional_claude_md": os.getenv("CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD")
    }}, handle)
""",
    )
    env = {
        **os.environ,
        "CLAUDE_REAL": str(fake_real),
        "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
    }
    code, _stdout, stderr = await _run(
        str(CLAUDE_LAUNCHER),
        "--system-prompt",
        "CUSTOM BASE",
        "--append-system-prompt",
        "USER APPEND",
        "--session-id",
        "11111111-1111-4111-8111-111111111111",
        "-p",
        "hello",
        env=env,
    )
    assert code == 0, stderr
    launched = json.loads(real_log.read_text())
    assert launched["argv"][0] == "--add-dir"
    canonical_directory = Path(launched["argv"][1])
    assert (canonical_directory / "CLAUDE.md").read_text() == canonical.read_text()
    assert (canonical_directory / "CLAUDE.md").stat().st_mode & 0o777 == 0o400
    assert canonical_directory.stat().st_mode & 0o777 == 0o500
    assert launched["argv"][2] == "--append-system-prompt-file"
    combined = Path(launched["argv"][3]).read_text()
    assert combined == "CUSTOM BASE\n\nUSER APPEND"
    assert canonical.read_text() not in combined
    assert launched["argv"][4:] == [
        "--session-id",
        "11111111-1111-4111-8111-111111111111",
        "-p",
        "hello",
    ]
    assert launched["hash"] == hashlib.sha256(canonical.read_bytes()).hexdigest()
    assert launched["contract"] == str(contract)
    assert launched["text"] == str(canonical)
    assert launched["additional_claude_md"] == "1"


@pytest.mark.asyncio
async def test_claude_launcher_records_aico_gpt_transport_metadata(
    tmp_path: Path,
) -> None:
    canonical = tmp_path / "canonical.md"
    canonical.write_text("AGENT HUB GPT CANONICAL")
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    settings = tmp_path / "claude-gpt-settings.json"
    settings.write_text(json.dumps({"model": "gpt-test-model"}))
    client_log = tmp_path / "client.json"
    real_log = tmp_path / "real.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
import hashlib, json, sys
payload = {canonical.read_text()!r}
with open({str(client_log)!r}, "w", encoding="utf-8") as handle:
    json.dump(sys.argv[1:], handle)
print(json.dumps({{
  "schema_version": "agent-hub.context.v1",
  "status": "ok",
  "payload_hash": hashlib.sha256(payload.encode()).hexdigest(),
  "delivery_id": "d",
  "artifact_id": "context-" + hashlib.sha256(payload.encode()).hexdigest(),
  "contract_path": {str(contract)!r},
  "text_path": {str(canonical)!r}
}}))
""",
    )
    fake_real = _executable(
        tmp_path / "claude-real",
        f"""#!/usr/bin/env python3
import json, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump(sys.argv[1:], handle)
""",
    )

    code, _stdout, stderr = await _run(
        str(CLAUDE_LAUNCHER),
        "--settings",
        str(settings),
        "-p",
        "native GPT task",
        env={
            **os.environ,
            "CLAUDE_REAL": str(fake_real),
            "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
            "AGENT_HUB_CONTEXT_PROVIDER": "openai",
            "AGENT_HUB_CONTEXT_TRANSPORT_VARIANT": "claude-gpt",
            "AICO_SESSION_ID": "aico-gpt-session",
        },
    )

    assert code == 0, stderr
    invoked = json.loads(client_log.read_text())
    assert invoked[invoked.index("--surface") + 1] == "claude_code"
    assert invoked[invoked.index("--provider") + 1] == "openai"
    assert invoked[invoked.index("--model") + 1] == "gpt-test-model"
    assert invoked[invoked.index("--session") + 1] == "aico-gpt-session"
    assert invoked[invoked.index("--metadata") + 1] == (
        "transport_variant=claude-gpt"
    )
    launched = json.loads(real_log.read_text())
    assert launched[-4:] == ["--settings", str(settings), "-p", "native GPT task"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("transport_variant", "native_label"),
    [(None, "Claude"), ("claude-gpt", "Claude GPT")],
)
async def test_claude_launcher_preserves_native_launch_on_failed_context(
    tmp_path: Path,
    transport_variant: str | None,
    native_label: str,
) -> None:
    failure = tmp_path / "failure.md"
    failure.write_text("<agent-hub-context-failure>STOP</agent-hub-context-failure>")
    contract = tmp_path / "contract.json"
    contract.write_text("{}")
    real_log = tmp_path / "real.json"
    fake_client = _executable(
        tmp_path / "context-client",
        f"""#!/usr/bin/env python3
import json
print(json.dumps({{
  "status": "failed",
  "payload_hash": "failed",
  "contract_path": {str(contract)!r},
  "text_path": {str(failure)!r}
}}))
raise SystemExit(2)
""",
    )
    fake_real = _executable(
        tmp_path / "claude-real",
        f"""#!/usr/bin/env python3
import json, os, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump({{
      "argv": sys.argv[1:],
      "hash": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH"),
      "contract": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_CONTRACT"),
      "text": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_TEXT"),
    }}, handle)
""",
    )
    environment = {
        **os.environ,
        "CLAUDE_REAL": str(fake_real),
        "AGENT_HUB_CONTEXT_CLIENT": str(fake_client),
    }
    if transport_variant:
        environment["AGENT_HUB_CONTEXT_TRANSPORT_VARIANT"] = transport_variant
    else:
        environment.pop("AGENT_HUB_CONTEXT_TRANSPORT_VARIANT", None)
    code, _stdout, stderr = await _run(
        str(CLAUDE_LAUNCHER),
        "-p",
        "native prompt still runs",
        env=environment,
    )

    assert code == 0
    assert f"continuing with native {native_label} context only" in stderr
    launched = json.loads(real_log.read_text())
    assert launched["argv"] == ["-p", "native prompt still runs"]
    assert launched["hash"] is None
    assert launched["contract"] is None
    assert launched["text"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("launcher", "real_env", "arguments", "native_name"),
    [
        (CLAUDE_LAUNCHER, "CLAUDE_REAL", ("-p", "native Claude task"), "Claude"),
        (CODEX_LAUNCHER, "CODEX_REAL", ("exec", "native Codex task"), "Codex"),
    ],
)
async def test_launchers_preserve_native_call_when_artifacts_cannot_be_written(
    tmp_path: Path,
    fake_context_cli: Path,
    launcher: Path,
    real_env: str,
    arguments: tuple[str, ...],
    native_name: str,
) -> None:
    blocked_root = tmp_path / "not-a-directory"
    blocked_root.write_text("file blocks artifact directory creation")
    real_log = tmp_path / "real.json"
    fake_real = _executable(
        tmp_path / "real-model",
        f"""#!/usr/bin/env python3
import json, os, sys
with open({str(real_log)!r}, "w", encoding="utf-8") as handle:
    json.dump({{
      "argv": sys.argv[1:],
      "hash": os.getenv("AGENT_HUB_CONTEXT_PREINJECTED_HASH"),
    }}, handle)
""",
    )

    code, _stdout, stderr = await _run(
        str(launcher),
        *arguments,
        env={
            **os.environ,
            real_env: str(fake_real),
            "AGENT_HUB_CONTEXT_CLIENT": str(CLIENT),
            "AGENT_HUB_CONTEXT_CLI": str(fake_context_cli),
            "AGENT_HUB_CONTEXT_ARTIFACT_ROOT": str(blocked_root),
        },
    )

    assert code == 0
    assert f"continuing with native {native_name} context only" in stderr
    launched = json.loads(real_log.read_text())
    assert launched["argv"] == list(arguments)
    assert launched["hash"] is None
