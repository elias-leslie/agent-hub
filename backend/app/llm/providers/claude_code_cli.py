"""Claude Code CLI provider.

Claude workloads run through the unmodified ``claude`` binary in headless print
mode, signed in with the owner's own Claude subscription. Anthropic permits
that route for scripts; it does not permit lifting the subscription OAuth token
into a custom Messages API client, so this provider never reads or forwards
Claude credentials. It is a pi-mono ``ApiProvider`` like every other provider.

Processes are isolated and tool-denied: no tools, MCP servers, skills,
settings, CLAUDE.md or session persistence, in a private empty working
directory. Agent Hub keeps the only tool loop, so a request that carries Agent
Hub tools fails fast and the agent's fallback chain takes it.

Persistent sessions: when ``options.session_id`` is set, one long-lived
``claude -p --input-format stream-json`` process serves the conversation
(``provider_support/claude_sessions.py``), keyed by session, model, effort and
system prompt. If the request is exactly the messages that process already
holds plus one new user message, only that message is written, so the prompt
cache grows by the delta instead of being rewritten each turn. Any mismatch
(edited history, branch, other model/effort/system prompt) or a missing
session_id starts a fresh process seeded with the transcript.

Typed outcomes: a safeguard refusal, a turn answered by another model, or a
subscription usage limit fails the turn (``stop_reason="error"``) and is
recorded as a ``ProviderOutcome``. Claude evaluates the whole conversation, so
after any failed, refused, substituted or aborted turn the process is killed
and evicted. ``CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK`` and ``switchModelsOnFlag``
keep the CLI from silently re-running a flagged request elsewhere.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..api_registry import register_api_provider
from ..event_stream import AssistantMessageEventStream
from ..provider_support.claude_code_cli import claude_binary
from ..provider_support.claude_sessions import ClaudeSession, claude_pool, pool_key
from ..provider_support.claude_stream import SYNTHETIC_MODEL, ClaudeTurnObserver, result_error
from ..types import (
    AssistantMessage,
    AudioContent,
    Context,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    Model,
    SimpleStreamOptions,
    StartEvent,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    ToolCall,
    ToolResultMessage,
    Usage,
    UserMessage,
)
from ..utils.outcomes import ProviderOutcome, record_outcome

API = "claude-code-cli"
_background_tasks: set[asyncio.Task[None]] = set()


class ClaudeCliError(RuntimeError):
    """A failed Claude Code CLI turn, worded for runtime failure classification."""


def _text_of(content: str | list[Any]) -> str:
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for block in content:
        if isinstance(block, TextContent):
            parts.append(block.text)
        elif isinstance(block, ImageContent):
            parts.append("[image]")
        elif isinstance(block, ToolCall):
            parts.append(f"[tool call {block.name}: {json.dumps(block.arguments)}]")
    return "\n".join(part for part in parts if part)


def _transcript_entry(message: Any) -> str:
    if isinstance(message, UserMessage):
        return f"<user>\n{_text_of(message.content)}\n</user>"
    if isinstance(message, ToolResultMessage):
        return f"<tool_result name=\"{message.tool_name}\">\n{_text_of(message.content)}\n</tool_result>"
    return f"<assistant>\n{_text_of(message.content)}\n</assistant>"


def _message_hash(message: Any) -> str:
    """Stable identity of a conversation message, ignoring thinking and timestamps."""
    parts = [type(message).__name__, _text_of(message.content)]
    if isinstance(message.content, list):
        parts += [hashlib.sha256(block.data.encode()).hexdigest() for block in message.content if isinstance(block, ImageContent)]
    return hashlib.sha256("\x00".join(parts).encode()).hexdigest()


def _user_turn(context: Context) -> dict[str, Any]:
    """Build the single stream-json user turn the CLI receives.

    Each CLI turn is stateless, so earlier conversation turns travel as a
    transcript ahead of the final user message, whose images stay native.
    """
    messages = list(context.messages)
    final = messages.pop() if messages and isinstance(messages[-1], UserMessage) else None
    blocks: list[dict[str, Any]] = []
    if messages:
        transcript = "\n\n".join(_transcript_entry(message) for message in messages)
        blocks.append({
            "type": "text",
            "text": f"<conversation_so_far>\n{transcript}\n</conversation_so_far>",
        })
    content = final.content if final is not None else ""
    for block in [TextContent(text=content)] if isinstance(content, str) else content:
        if isinstance(block, TextContent) and block.text:
            blocks.append({"type": "text", "text": block.text})
        elif isinstance(block, ImageContent):
            blocks.append({
                "type": "image",
                "source": {"type": "base64", "media_type": block.mime_type, "data": block.data},
            })
        elif isinstance(block, AudioContent):
            raise ClaudeCliError("Claude models do not accept audio input")
    if not blocks:
        raise ClaudeCliError("Claude Code CLI request has no user content")
    return {"type": "user", "message": {"role": "user", "content": blocks}}


def _argv(binary: str, model: Model[Any], options: SimpleStreamOptions | None, prompt_file: Path | None) -> list[str]:
    argv = [
        binary, "-p",
        "--model", model.id,
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose",
        "--include-partial-messages",
        "--safe-mode",
        "--disable-slash-commands",
        "--exclude-dynamic-system-prompt-sections",
        "--tools", "",
        "--setting-sources", "",
        # The owner's setting: a safety-flagged request fails instead of being
        # re-run on another model, so the served model always matches the route.
        "--settings", '{"switchModelsOnFlag": false}',
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if prompt_file is not None:
        argv += ["--system-prompt-file", str(prompt_file)]
    effort = _effort(model, options)
    if effort is not None:
        argv += ["--effort", effort]
    return argv


def _apply_usage(output: AssistantMessage, model: Model[Any], raw: dict[str, Any]) -> None:
    usage = Usage(
        input=int(raw.get("input_tokens") or 0),
        output=int(raw.get("output_tokens") or 0),
        cache_read=int(raw.get("cache_read_input_tokens") or 0),
        cache_write=int(raw.get("cache_creation_input_tokens") or 0),
    )
    usage.total_tokens = usage.input + usage.output + usage.cache_read + usage.cache_write
    cost = usage.cost
    cost.input = usage.input * model.cost.input / 1_000_000
    cost.output = usage.output * model.cost.output / 1_000_000
    cost.cache_read = usage.cache_read * model.cost.cache_read / 1_000_000
    cost.cache_write = usage.cache_write * model.cost.cache_write / 1_000_000
    cost.total = cost.input + cost.output + cost.cache_read + cost.cache_write
    output.usage = usage


class _TurnFailure(ClaudeCliError):
    """A failed turn whose cause is a typed provider outcome."""

    def __init__(self, message: str, outcome: ProviderOutcome) -> None:
        super().__init__(message)
        self.outcome = outcome


class _Aborted(Exception):
    pass


class _TurnState(ClaudeTurnObserver):
    def __init__(self, stream: AssistantMessageEventStream, output: AssistantMessage, model: Model[Any]) -> None:
        super().__init__()
        self.stream = stream
        self.output = output
        self.model = model
        self.blocks: dict[int, int] = {}

    def handle(self, event: dict[str, Any]) -> None:
        if event.get("type") == "stream_event":
            self._stream_event(event.get("event") or {})
        else:
            super().handle(event)

    def _result(self, event: dict[str, Any]) -> None:
        super()._result(event)
        if isinstance(event.get("usage"), dict):
            _apply_usage(self.output, self.model, event["usage"])

    def _assistant(self, event: dict[str, Any]) -> None:
        super()._assistant(event)
        message = event.get("message") or {}
        name = message.get("model")
        if name and name != SYNTHETIC_MODEL:
            self.output.response_model = str(name)
            if message.get("id"):
                self.output.response_id = str(message["id"])

    def fill_from_message(self) -> None:
        """Use the final assistant message when the CLI streamed no partial blocks."""
        if self.output.content or not self.answer_text:
            return
        text = "\n".join(self.answer_text)
        self.output.content.append(TextContent(text=text))
        self.stream.push(TextStartEvent(content_index=0, partial=self.output))
        self.stream.push(TextDeltaEvent(content_index=0, delta=text, partial=self.output))
        self.stream.push(TextEndEvent(content_index=0, content=text, partial=self.output))

    def _stream_event(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        index = event.get("index")
        if kind == "content_block_start" and isinstance(index, int):
            block_type = (event.get("content_block") or {}).get("type")
            position = len(self.output.content)
            if block_type == "text":
                self.output.content.append(TextContent(text=""))
                self.blocks[index] = position
                self.stream.push(TextStartEvent(content_index=position, partial=self.output))
            elif block_type == "thinking":
                self.output.content.append(ThinkingContent(thinking=""))
                self.blocks[index] = position
                self.stream.push(ThinkingStartEvent(content_index=position, partial=self.output))
        elif kind == "content_block_delta" and index in self.blocks:
            position = self.blocks[index]
            delta = event.get("delta") or {}
            block = self.output.content[position]
            if delta.get("type") == "text_delta" and isinstance(block, TextContent):
                block.text += delta.get("text", "")
                self.stream.push(TextDeltaEvent(content_index=position, delta=delta.get("text", ""), partial=self.output))
            elif delta.get("type") == "thinking_delta" and isinstance(block, ThinkingContent):
                block.thinking += delta.get("thinking", "")
                self.stream.push(ThinkingDeltaEvent(content_index=position, delta=delta.get("thinking", ""), partial=self.output))
            elif delta.get("type") == "signature_delta" and isinstance(block, ThinkingContent):
                block.thinking_signature = (block.thinking_signature or "") + delta.get("signature", "")
        elif kind == "content_block_stop" and index in self.blocks:
            position = self.blocks.pop(index)
            block = self.output.content[position]
            if isinstance(block, TextContent):
                self.stream.push(TextEndEvent(content_index=position, content=block.text, partial=self.output))
            elif isinstance(block, ThinkingContent):
                self.stream.push(ThinkingEndEvent(content_index=position, content=block.thinking, partial=self.output))
        elif kind == "message_delta":
            stop_reason = (event.get("delta") or {}).get("stop_reason")
            if stop_reason == "max_tokens":
                self.output.stop_reason = "length"


async def _read_line(stdout: asyncio.StreamReader, abort: asyncio.Event | None) -> bytes:
    """Read one stdout line; raise ``_Aborted`` as soon as ``abort`` is set."""
    if abort is None:
        return await stdout.readline()
    if abort.is_set():
        raise _Aborted
    read = asyncio.ensure_future(stdout.readline())
    stop = asyncio.ensure_future(abort.wait())
    try:
        await asyncio.wait({read, stop}, return_when=asyncio.FIRST_COMPLETED)
    finally:
        stop.cancel()
        if not read.done():
            read.cancel()
    if not read.done() or read.cancelled():
        raise _Aborted
    return read.result()


async def _read_turn(session: ClaudeSession, state: _TurnState, abort: asyncio.Event | None) -> None:
    """Feed stdout events to ``state`` until the turn's ``result`` event (or EOF)."""
    assert session.process.stdout is not None
    while line := await _read_line(session.process.stdout, abort):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            state.handle(event)
            if event.get("type") == "result":
                return


async def _run(
    stream: AssistantMessageEventStream,
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None,
) -> None:
    output = AssistantMessage(
        content=[],
        api=model.api,
        provider=model.provider,
        model=model.id,
        usage=Usage(),
        stop_reason="stop",
        timestamp=int(time.time() * 1000),
    )
    stream.push(StartEvent(partial=output))
    session: ClaudeSession | None = None
    keep = False
    try:
        if context.tools:
            raise ClaudeCliError(
                "Claude Code CLI runs tool-denied; requests with Agent Hub tools need a tool-capable model"
            )
        binary = claude_binary()
        if binary is None:
            raise ClaudeCliError("Claude Code CLI is not installed on this host")
        messages = list(context.messages)
        hashes = [_message_hash(message) for message in messages]
        key = None
        if options is not None and options.session_id:
            effort = _effort(model, options)
            key = pool_key(options.session_id, model.id, effort, context.system_prompt)
            session = await claude_pool.checkout(key)
        continued = (
            session is not None
            and bool(messages)
            and isinstance(messages[-1], UserMessage)
            and session.seen == hashes[:-1]
        )
        if session is not None and not continued:
            await claude_pool.discard(session)
            session = None
        if session is None:
            session = await ClaudeSession.start(
                key, context.system_prompt, lambda prompt_file: _argv(binary, model, options, prompt_file)
            )
            await claude_pool.add(session)
        turn = json.dumps(_user_turn(replace(context, messages=messages[-1:]) if continued else context)) + "\n"
        state = _TurnState(stream, output, model)
        process = session.process
        assert process.stdin is not None
        process.stdin.write(turn.encode("utf-8"))
        await process.stdin.drain()
        # No deadline on the turn: the CLI ends it by its own result, a real error, or the abort signal. A request's
        # ``timeout_ms`` bounds a wire read elsewhere; a total time limit here would kill a model still working.
        await _read_turn(session, state, options.signal if options else None)
        if state.result is None:
            await process.wait()
        typed = state.outcome(model.id)
        if typed is not None:
            raise _TurnFailure(typed[1], typed[0])
        error = result_error(state.result, process.returncode, session.stderr_tail)
        if error is not None:
            raise ClaudeCliError(error)
        state.fill_from_message()
        stream.push(DoneEvent(reason="length" if output.stop_reason == "length" else "stop", message=output))
        session.seen = [*hashes, _message_hash(output)]
        keep = key is not None
    except _Aborted:
        stream.push(ErrorEvent(reason="aborted", error=replace(
            output, stop_reason="aborted", error_message="Request was aborted"
        )))
    except Exception as exc:
        error = replace(output, stop_reason="error", error_message=str(exc))
        if isinstance(exc, _TurnFailure):
            record_outcome(error, exc.outcome)
        stream.push(ErrorEvent(reason="error", error=error))
    finally:
        if session is not None:
            if keep:
                claude_pool.release(session, session.seen)
            else:
                await claude_pool.discard(session)


def _effort(model: Model[Any], options: SimpleStreamOptions | None) -> str | None:
    if options is None or not options.reasoning:
        return None
    effort = (model.thinking_level_map or {}).get(options.reasoning, options.reasoning)
    if effort is None:
        raise ClaudeCliError(f"{model.id} does not support {options.reasoning} reasoning")
    return effort


class _ClaudeCodeCliProvider:
    api = API
    # The CLI's own system prompt states the served model, so Agent Hub adds no identity line.
    states_own_model = True

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        stream = AssistantMessageEventStream()
        task = asyncio.create_task(_run(stream, model, context, options))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
        return stream

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return self.stream(model, context, options)


claude_code_cli_provider = _ClaudeCodeCliProvider()
register_api_provider(claude_code_cli_provider)
