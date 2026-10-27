"""Headless Claude Code CLI provider: isolation, request shape and failure wording."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from app.llm.model_resolver import resolve_llm_model
from app.llm.provider_support import claude_sessions
from app.llm.provider_support.claude_code_cli import child_env
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
from app.llm.utils.outcomes import ProviderOutcome, outcome_of
from app.services.model_runtime_health import classify_runtime_failure


def _user(content) -> UserMessage:
    return UserMessage(content=content, timestamp=0)


def test_argv_is_tool_denied_isolated_and_maps_effort(tmp_path) -> None:
    model = resolve_llm_model("claude-sonnet-5-5", "claude")
    argv = cli._argv("claude", model, SimpleStreamOptions(reasoning="minimal"), tmp_path / "p.md")
    assert argv[argv.index("--tools") + 1] == ""
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert json.loads(argv[argv.index("--settings") + 1]) == {"switchModelsOnFlag": False}
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


FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "claude_code_cli"


def _fixture(name: str) -> list[dict]:
    return [json.loads(line) for line in (FIXTURES / f"{name}.jsonl").read_text().splitlines()]


def _turn(name: str) -> list[dict]:
    """A fixture's events closed by the ``result`` event every real turn ends with."""
    return [*_fixture(name), {"type": "result", "subtype": "success", "is_error": False, "result": ""}]


def _success(text: str) -> list[dict]:
    """The real continuation-turn fixture with this turn's answer text."""
    events = copy.deepcopy(_fixture("success_continuation_turn"))
    events[1]["message"]["content"][0]["text"] = text
    events[3]["result"] = text
    return events


class FakeProcess:
    """A stream-json CLI: each stdin user message releases the next scripted turn on stdout."""

    def __init__(self, turns: list[list[dict]]) -> None:
        self.turns = list(turns)
        self.writes: list[dict] = []
        self.returncode: int | None = None
        self.stdin = self
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()

    def write(self, data: bytes) -> None:
        self.writes.append(json.loads(data))
        for event in self.turns.pop(0):
            self.stdout.feed_data((json.dumps(event) + "\n").encode())

    async def drain(self) -> None:
        return None

    def kill(self) -> None:
        self.returncode = -9
        self.stdout.feed_eof()
        self.stderr.feed_eof()

    async def wait(self) -> int:
        return self.returncode if self.returncode is not None else 0


@pytest.fixture
def cli_world(monkeypatch):
    """Patch the CLI launch; ``spawn(*turns)`` queues one process per call, in order."""
    queued: list[FakeProcess] = []
    launched: list[tuple[FakeProcess, tuple[str, ...], dict]] = []

    async def fake_create_process(*argv, **kwargs):
        process = queued.pop(0)
        launched.append((process, argv, kwargs))
        return process

    monkeypatch.setattr(claude_sessions, "create_process", fake_create_process)
    monkeypatch.setattr(cli, "claude_binary", lambda: "claude")

    def spawn(*turns: list[dict]) -> FakeProcess:
        process = FakeProcess(list(turns))
        queued.append(process)
        return process

    yield spawn, launched
    for process, _, _ in launched:
        process.kill()
    claude_sessions.claude_pool._sessions.clear()


async def _ask(messages, *, model_id="claude-haiku-5-5", session_id="s1", system="sys", signal=None):
    model = resolve_llm_model(model_id, "claude")
    options = SimpleStreamOptions(session_id=session_id, signal=signal)
    stream = cli.claude_code_cli_provider.stream(model, Context(messages=messages, system_prompt=system), options)
    return await stream.result()


def _outcome(message: AssistantMessage) -> ProviderOutcome:
    outcome = outcome_of(message)
    assert outcome is not None
    return outcome


def _block_texts(write: dict) -> list[str]:
    return [block["text"] for block in write["message"]["content"]]


@pytest.mark.asyncio
async def test_continuation_writes_only_the_new_user_message(cli_world) -> None:
    spawn, launched = cli_world
    process = spawn(_success("one"), _success("two"), _success("three"))
    u1, u2, u3 = _user("first"), _user("second"), _user("third")
    a1 = await _ask([u1])
    a2 = await _ask([u1, a1, u2])
    a3 = await _ask([u1, a1, u2, a2, u3])
    assert [m.content[0].text for m in (a1, a2, a3)] == ["one", "two", "three"]
    assert a1.response_model == "claude-haiku-5-5"
    assert len(launched) == 1
    assert [_block_texts(w) for w in process.writes] == [["first"], ["second"], ["third"]]
    assert a2.usage.cache_write == 626


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["edited", "branch", "model", "system", "no_session"])
async def test_mismatch_starts_a_fresh_seeded_process(cli_world, change) -> None:
    spawn, launched = cli_world
    first = spawn(_success("one"), _success("unused"))
    u1, u2 = _user("first"), _user("second")
    a1 = await _ask([u1])
    second = spawn(_success("two"))
    kwargs = {}
    history = [u1, a1, u2]
    if change == "edited":
        history = [_user("first, edited"), a1, u2]
    elif change == "branch":
        history = [u1, replace_text(a1, "another reply"), u2]
    elif change == "model":
        kwargs["model_id"] = "claude-sonnet-5-5"
    elif change == "system":
        kwargs["system"] = "other system prompt"
    elif change == "no_session":
        kwargs["session_id"] = None
    await _ask(history, **kwargs)
    assert len(launched) == 2
    assert "<conversation_so_far>" in second.writes[0]["message"]["content"][0]["text"]
    assert _block_texts(second.writes[0])[-1] == "second"
    if change not in ("model", "system"):
        assert first.returncode == -9 or change == "no_session"


def replace_text(message: AssistantMessage, text: str) -> AssistantMessage:
    return AssistantMessage(
        content=[TextContent(text=text)], api=message.api, provider=message.provider, model=message.model,
        usage=Usage(), stop_reason="stop", timestamp=0,
    )


@pytest.mark.asyncio
async def test_one_shot_requests_do_not_keep_a_process(cli_world) -> None:
    spawn, _ = cli_world
    first = spawn(_success("one"))
    await _ask([_user("hi")], session_id=None)
    assert first.returncode == -9
    assert claude_sessions.claude_pool._sessions == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("name", "kind", "category", "served"),
    [
        ("refusal_assistant", "refused", "cyber", None),
        ("safeguards_informational", "refused", None, None),
        ("model_refusal_fallback", "substituted", "cyber", "claude-opus-4-8"),
    ],
)
async def test_fixtures_classify_and_evict_the_session(cli_world, name, kind, category, served) -> None:
    spawn, launched = cli_world
    poisoned = spawn(_turn(name))
    result = await _ask([_user("hi")], model_id="claude-opus-5-5")
    assert result.stop_reason == "error"
    outcome = outcome_of(result)
    assert outcome is not None
    assert (outcome.kind, outcome.category, outcome.served_model, outcome.requested_model) == (
        kind, category, served, "claude-opus-5-5",
    )
    assert result.error_message
    assert poisoned.returncode == -9
    assert claude_sessions.claude_pool._sessions == {}
    spawn(_success("fresh"))
    await _ask([_user("again")], model_id="claude-opus-5-5")
    assert len(launched) == 2


@pytest.mark.asyncio
async def test_refusal_fixture_carries_request_id_and_explanation(cli_world) -> None:
    spawn, _ = cli_world
    spawn(_turn("refusal_assistant"))
    outcome = _outcome(await _ask([_user("hi")], model_id="claude-opus-5-5"))
    assert outcome.request_id == "req_FIXTURE"
    assert "cyber content" in (outcome.explanation or "")
    spawn(_turn("model_refusal_fallback"))
    outcome = _outcome(await _ask([_user("hi")], model_id="claude-opus-5-5", session_id="s2"))
    assert outcome.request_id == "req_FIXTURE"
    assert outcome.explanation


@pytest.mark.asyncio
async def test_a_served_model_other_than_requested_is_a_typed_substitution(cli_world) -> None:
    spawn, _ = cli_world
    events = _success("answer")
    events[1]["message"]["model"] = "claude-haiku-4-8"
    events[3]["modelUsage"] = {"claude-haiku-4-8": events[3]["modelUsage"]["claude-haiku-5-5"]}
    spawn(events)
    result = await _ask([_user("hi")])
    assert result.stop_reason == "error"
    assert outcome_of(result) == ProviderOutcome(
        kind="substituted", requested_model="claude-haiku-5-5", served_model="claude-haiku-4-8"
    )
    assert "claude-haiku-4-8" in result.error_message and "claude-haiku-5-5" in result.error_message


@pytest.mark.asyncio
async def test_usage_limit_is_typed_and_classified_for_routing(cli_world) -> None:
    spawn, _ = cli_world
    spawn(_fixture("usage_limit"))
    result = await _ask([_user("hi")])
    outcome = _outcome(result)
    assert (outcome.kind, outcome.window, outcome.resets_at) == ("usage_limit", "five_hour", 1793155200)
    assert classify_runtime_failure(RuntimeError(result.error_message)).smoke_status == "quota_or_rate_limited"


@pytest.mark.asyncio
async def test_result_level_refusal_signals_are_detected(cli_world) -> None:
    spawn, _ = cli_world
    result_event = {"type": "result", "subtype": "success", "is_error": True, "stop_reason": "refusal", "result": ""}
    spawn([result_event])
    outcome = outcome_of(await _ask([_user("hi")]))
    assert outcome is not None and outcome.kind == "refused"


@pytest.mark.asyncio
async def test_abort_kills_and_evicts_the_process(cli_world) -> None:
    spawn, _ = cli_world
    process = spawn([])
    signal = asyncio.Event()
    task = asyncio.create_task(_ask([_user("hi")], signal=signal))
    await asyncio.sleep(0.05)
    signal.set()
    result = await task
    assert result.stop_reason == "aborted"
    assert process.returncode == -9
    assert claude_sessions.claude_pool._sessions == {}


def test_child_env_disables_refusal_fallback() -> None:
    assert child_env()["CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK"] == "1"


@pytest.mark.asyncio
async def test_pool_cap_and_idle_expiry_come_from_settings(cli_world, monkeypatch) -> None:
    from app.config import settings

    spawn, _ = cli_world
    monkeypatch.setattr(settings, "claude_session_pool_max", 1)
    monkeypatch.setattr(settings, "claude_session_idle_seconds", 0.05)
    one, two = spawn(_success("a")), spawn(_success("b"))
    await _ask([_user("x")], session_id="s1")
    await _ask([_user("y")], session_id="s2")
    assert one.returncode == -9
    assert list(claude_sessions.claude_pool._sessions) == [claude_sessions.pool_key("s2", "claude-haiku-5-5", None, "sys")]
    await asyncio.sleep(0.2)
    assert two.returncode == -9
    assert claude_sessions.claude_pool._sessions == {}
