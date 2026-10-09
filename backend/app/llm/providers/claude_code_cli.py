"""Claude Code CLI provider.

Claude workloads run through the unmodified ``claude`` binary in headless print
mode, signed in with the owner's own Claude subscription. Anthropic permits
that route for scripts; it does not permit lifting the subscription OAuth token
into a custom Messages API client, so this provider never reads or forwards
Claude credentials. It is a pi-mono ``ApiProvider`` like every other provider.

Each request starts one isolated, tool-denied CLI turn: no tools, MCP servers,
skills, settings, CLAUDE.md or session persistence, in a private empty working
directory. Agent Hub keeps the only tool loop, so a request that carries Agent
Hub tools fails fast and the agent's fallback chain takes it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import tempfile
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from app.utils.safe_subprocess import create_process

from ..api_registry import register_api_provider
from ..event_stream import AssistantMessageEventStream
from ..provider_support.claude_code_cli import child_env, claude_binary
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

API = "claude-code-cli"
_STREAM_LIMIT = 64 * 1024 * 1024
_STDERR_TAIL = 2_000
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
        "--strict-mcp-config",
        "--no-session-persistence",
    ]
    if prompt_file is not None:
        argv += ["--system-prompt-file", str(prompt_file)]
    if options is not None and options.reasoning:
        effort = (model.thinking_level_map or {}).get(options.reasoning, options.reasoning)
        if effort is None:
            raise ClaudeCliError(f"{model.id} does not support {options.reasoning} reasoning")
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


def _rate_limit_message(info: dict[str, Any]) -> str | None:
    status = str(info.get("status") or "")
    if status in ("", "allowed", "allowed_warning"):
        return None
    window = info.get("rateLimitType") or "subscription"
    resets_at = info.get("resetsAt")
    reset = f"; resets at unix {resets_at}" if resets_at else ""
    return f"429 rate limit: Claude {window} usage limit reached ({status}){reset}"


class _TurnState:
    def __init__(self, stream: AssistantMessageEventStream, output: AssistantMessage) -> None:
        self.stream = stream
        self.output = output
        self.blocks: dict[int, int] = {}
        self.rate_limit_error: str | None = None
        self.result: dict[str, Any] | None = None

    def handle(self, event: dict[str, Any], model: Model[Any]) -> None:
        kind = event.get("type")
        if kind == "stream_event":
            self._stream_event(event.get("event") or {})
        elif kind == "assistant":
            message = event.get("message") or {}
            if message.get("model"):
                self.output.response_model = str(message["model"])
            if message.get("id"):
                self.output.response_id = str(message["id"])
        elif kind == "rate_limit_event":
            self.rate_limit_error = _rate_limit_message(event.get("rate_limit_info") or {})
        elif kind == "result":
            self.result = event
            if isinstance(event.get("usage"), dict):
                _apply_usage(self.output, model, event["usage"])

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


def _result_error(result: dict[str, Any] | None, returncode: int | None, stderr: str) -> str | None:
    if result is not None and not result.get("is_error") and result.get("subtype") == "success":
        return None
    detail = ""
    if result is not None:
        detail = str(result.get("result") or "; ".join(map(str, result.get("errors") or [])) or result.get("subtype") or "")
    detail = detail or stderr.strip()[-_STDERR_TAIL:] or f"exit status {returncode}"
    lowered = detail.lower()
    if "not logged in" in lowered or "/login" in lowered or ("oauth" in lowered and "expired" in lowered):
        return f"401 unauthorized: Claude Code CLI is not signed in ({detail})"
    if "issue with the selected model" in lowered:
        return f"model_not_found: {detail}"
    return f"Claude Code CLI failed: {detail}"


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
    process: asyncio.subprocess.Process | None = None
    try:
        if context.tools:
            raise ClaudeCliError(
                "Claude Code CLI runs tool-denied; requests with Agent Hub tools need a tool-capable model"
            )
        binary = claude_binary()
        if binary is None:
            raise ClaudeCliError("Claude Code CLI is not installed on this host")
        turn = json.dumps(_user_turn(context)) + "\n"
        with tempfile.TemporaryDirectory(prefix="agent-hub-claude-") as workdir:
            prompt_file = None
            if context.system_prompt:
                prompt_file = Path(workdir) / "system-prompt.md"
                prompt_file.write_text(context.system_prompt, encoding="utf-8")
            run_dir = Path(workdir) / "run"
            run_dir.mkdir(mode=0o700)
            process = await create_process(
                *_argv(binary, model, options, prompt_file),
                working_dir=run_dir,
                env=child_env(),
                stdin=asyncio.subprocess.PIPE,
                limit=_STREAM_LIMIT,
            )
            state = _TurnState(stream, output)
            stderr_task = asyncio.create_task(process.stderr.read()) if process.stderr else None
            assert process.stdin is not None and process.stdout is not None
            process.stdin.write(turn.encode("utf-8"))
            await process.stdin.drain()
            process.stdin.close()
            timeout = options.timeout_ms / 1000 if options and options.timeout_ms else None
            async with asyncio.timeout(timeout):
                async for line in process.stdout:
                    if options is not None and options.signal is not None and options.signal.is_set():
                        stream.push(ErrorEvent(reason="aborted", error=replace(
                            output, stop_reason="aborted", error_message="Request was aborted"
                        )))
                        return
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if isinstance(event, dict):
                        state.handle(event, model)
                returncode = await process.wait()
            stderr = (await stderr_task).decode("utf-8", errors="replace") if stderr_task else ""
        error = _result_error(state.result, returncode, stderr)
        if error is not None:
            raise ClaudeCliError(state.rate_limit_error or error)
        stream.push(DoneEvent(reason="length" if output.stop_reason == "length" else "stop", message=output))
    except TimeoutError:
        error = replace(output, stop_reason="error", error_message="Claude Code CLI turn timed out")
        stream.push(ErrorEvent(reason="error", error=error))
    except Exception as exc:
        error = replace(output, stop_reason="error", error_message=str(exc))
        stream.push(ErrorEvent(reason="error", error=error))
    finally:
        if process is not None and process.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()


class _ClaudeCodeCliProvider:
    api = API

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
