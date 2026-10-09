"""Headless Claude Code CLI provider: isolation, request shape and failure wording."""

from __future__ import annotations

import pytest

from app.llm.model_resolver import resolve_llm_model
from app.llm.providers import claude_code_cli as cli
from app.llm.types import (
    AssistantMessage,
    AudioContent,
    Context,
    ImageContent,
    SimpleStreamOptions,
    TextContent,
    Tool,
    Usage,
    UserMessage,
)
from app.services.model_runtime_health import classify_runtime_failure


def _user(content) -> UserMessage:
    return UserMessage(content=content, timestamp=0)


def test_argv_is_tool_denied_isolated_and_maps_effort(tmp_path) -> None:
    model = resolve_llm_model("claude-sonnet-5-5", "claude")
    argv = cli._argv("claude", model, SimpleStreamOptions(reasoning="minimal"), tmp_path / "p.md")
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    for flag in ("--safe-mode", "--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--model") + 1] == "claude-sonnet-5-5"
    assert argv[argv.index("--effort") + 1] == "low"
    assert argv[argv.index("--system-prompt-file") + 1] == str(tmp_path / "p.md")


def test_history_travels_as_transcript_and_images_stay_native() -> None:
    earlier = AssistantMessage(
        content=[TextContent(text="Hi Ada.")], api="x", provider="claude", model="m",
        usage=Usage(), stop_reason="stop", timestamp=0,
    )
    turn = cli._user_turn(Context(messages=[
        _user("My name is Ada."),
        earlier,
        _user([ImageContent(data="QUJD", mime_type="image/png"), TextContent(text="Name?")]),
    ]))
    blocks = turn["message"]["content"]
    assert "<user>\nMy name is Ada.\n</user>" in blocks[0]["text"]
    assert "<assistant>\nHi Ada.\n</assistant>" in blocks[0]["text"]
    assert blocks[1] == {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "QUJD"}}
    assert blocks[2] == {"type": "text", "text": "Name?"}


def test_audio_is_refused_before_launch() -> None:
    with pytest.raises(cli.ClaudeCliError, match="audio"):
        cli._user_turn(Context(messages=[_user([AudioContent(data="QQ==", mime_type="audio/wav")])]))


@pytest.mark.asyncio
async def test_agent_hub_tools_fail_fast_for_the_fallback_chain() -> None:
    model = resolve_llm_model("claude-haiku-5-5", "claude")
    context = Context(messages=[_user("hi")], tools=[Tool(name="t", description="d", parameters={})])
    stream = cli.claude_code_cli_provider.stream(model, context)
    result = await stream.result()
    assert result.stop_reason == "error"
    assert "tool-denied" in (result.error_message or "")


def test_failures_are_worded_for_runtime_classification() -> None:
    signed_out = cli._result_error({"is_error": True, "result": "Not logged in · Please run /login"}, 1, "")
    assert classify_runtime_failure(RuntimeError(signed_out)).smoke_status == "auth_failed"
    limited = cli._rate_limit_message({"status": "rejected", "rateLimitType": "five_hour", "resetsAt": 1})
    assert classify_runtime_failure(RuntimeError(limited)).smoke_status == "quota_or_rate_limited"
    assert cli._rate_limit_message({"status": "allowed"}) is None
    assert cli._result_error({"subtype": "success", "is_error": False}, 0, "") is None


def test_a_substituted_model_is_an_error_not_a_misattributed_answer() -> None:
    model = resolve_llm_model("claude-opus-5-5", "claude")
    def served(name: str | None) -> AssistantMessage:
        return AssistantMessage(
            content=[], api="x", provider="claude", model=model.id, usage=Usage(),
            stop_reason="stop", timestamp=0, response_model=name,
        )
    assert cli._substitution_error(model, served("claude-opus-5-5")) is None
    assert cli._substitution_error(model, served("claude-opus-5-5-20260922")) is None
    assert cli._substitution_error(model, served(None)) is None
    message = cli._substitution_error(model, served("claude-opus-4-8"))
    assert message and "claude-opus-4-8" in message and "claude-opus-5-5" in message
