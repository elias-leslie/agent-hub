"""Claude adapter — uses Claude Agent SDK (Max subscription, zero API cost).

All operations go through the Claude CLI / Agent SDK, which handles
authentication via the Max subscription.  No per-token API billing.
"""

import asyncio
import json
import logging
import shutil
import time
from collections.abc import AsyncIterator
from typing import Any

from app.adapters.base import (
    CacheMetrics,
    CompletionResult,
    Message,
    ProviderAdapter,
    ProviderError,
    StreamEvent,
)

logger = logging.getLogger(__name__)

# Tools built into Claude Code CLI — skip when building MCP server
_CLI_BUILTIN_TOOLS = frozenset({"bash", "read_file", "write_file"})

_MCP_RACE_PATCHED = False


def _patch_sdk_mcp_race_condition() -> None:
    """Patch SDK race condition where MCP control response writes fail during shutdown."""
    global _MCP_RACE_PATCHED
    if _MCP_RACE_PATCHED:
        return
    _MCP_RACE_PATCHED = True
    try:
        from claude_agent_sdk._errors import CLIConnectionError
        from claude_agent_sdk._internal.query import Query

        original = Query._handle_control_request

        async def _safe_handle_control_request(self: Any, request: Any) -> None:
            try:
                await original(self, request)
            except CLIConnectionError:
                logger.debug("MCP control response write failed (transport closed during shutdown)")
            except Exception:
                logger.debug("MCP control request error during shutdown", exc_info=True)

        Query._handle_control_request = _safe_handle_control_request  # type: ignore[assignment]
        logger.info("Patched SDK MCP race condition in Query._handle_control_request")
    except Exception:
        logger.warning("Failed to patch SDK MCP race condition", exc_info=True)


def _build_can_use_tool(checker: Any) -> Any:
    """Build a can_use_tool callback mapping PermissionChecker decisions to SDK types."""
    from claude_agent_sdk.types import (
        PermissionResultAllow,
        PermissionResultDeny,
        ToolPermissionContext,
    )

    from app.services.tools.base import ToolCall, ToolDecision

    async def can_use_tool(
        tool_name: str,
        tool_input: dict[str, Any],
        context: ToolPermissionContext,
    ) -> PermissionResultAllow | PermissionResultDeny:
        tool_call = ToolCall(id="", name=tool_name, input=tool_input)
        decision = await checker.check(tool_call)
        if decision == ToolDecision.ALLOW:
            return PermissionResultAllow()
        elif decision == ToolDecision.DENY:
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' denied by permission config"
            )
        else:  # ASK — deny in autonomous mode (no user to confirm)
            return PermissionResultDeny(
                message=f"Tool '{tool_name}' requires confirmation (autonomous mode)"
            )

    return can_use_tool


def _build_mcp_server(
    tools: list[dict[str, Any]],
    working_dir: str | None,
    project_id: str | None,
) -> Any | None:
    """Build an in-process SDK MCP server for custom tools.

    Registers non-CLI-builtin tools as MCP tools backed by DirectToolExecutor.
    Returns None if no custom tools to register.
    """
    from claude_agent_sdk import create_sdk_mcp_server
    from claude_agent_sdk import tool as sdk_tool

    from app.services.tools.direct_executor_core import DirectToolExecutor

    custom_tools = [t for t in tools if t["name"] not in _CLI_BUILTIN_TOOLS]
    if not custom_tools:
        return None

    _patch_sdk_mcp_race_condition()

    executor = DirectToolExecutor(working_dir, project_id=project_id)
    mcp_tools = []
    for t in custom_tools:
        tool_name = t["name"]

        async def handler(args: dict[str, Any], _name: str = tool_name) -> dict[str, Any]:
            try:
                result = await executor.dispatch(_name, args)
                return {"content": [{"type": "text", "text": result}]}
            except Exception as e:
                logger.exception("MCP handler error: tool=%s", _name)
                return {"content": [{"type": "text", "text": f"Error: {e}"}], "is_error": True}

        mcp_tools.append(sdk_tool(tool_name, t["description"], t["input_schema"])(handler))

    return create_sdk_mcp_server("agent-hub-tools", tools=mcp_tools)


async def _wrap_prompt_as_stream(prompt: str) -> Any:
    """Wrap a string prompt as an async iterable for SDK streaming mode."""

    async def _stream() -> Any:
        yield {
            "type": "user",
            "message": {"role": "user", "content": prompt},
            "parent_tool_use_id": None,
            "session_id": None,
        }

    return _stream()


def _build_claude_model_map() -> dict[str, str]:
    """Build model ID/alias → SDK short name map from catalog."""
    from app.constants.catalog import MODEL_CATALOG

    m: dict[str, str] = {}
    for entry in MODEL_CATALOG:
        if entry.provider == "claude":
            m[entry.id] = entry.alias      # "claude-sonnet-4-6" → "sonnet"
            m[entry.alias] = entry.alias    # "sonnet" → "sonnet"
    return m


_CLAUDE_MODEL_MAP: dict[str, str] = _build_claude_model_map()


class ClaudeAdapter(ProviderAdapter):
    """Adapter for Claude models via Claude Agent SDK (Max subscription).

    All operations go through the Claude CLI which handles auth via the
    Max subscription.  No per-token API cost.
    """

    def __init__(self, **kwargs: Any):
        """Initialize Claude adapter.  Requires Claude CLI."""
        self._cli_path = shutil.which("claude")
        if not self._cli_path:
            raise ValueError(
                "Claude adapter requires the Claude CLI. "
                "Install: npm install -g @anthropic-ai/claude-code"
            )
        logger.info("Claude adapter: CLI (%s)", self._cli_path)

    @property
    def provider_name(self) -> str:
        return "claude"

    async def complete(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> CompletionResult:
        """Non-streaming completion via Claude SDK."""
        from app.adapters.claude_utils import (
            _sdk_semaphore,
            build_sdk_options,
            extract_block_content,
            extract_json_from_response,
            extract_system_and_conversation,
        )
        from app.adapters.errors import with_retry

        start_time = time.time()
        sdk_model = _CLAUDE_MODEL_MAP.get(model, model)
        response_format = kwargs.get("response_format") or {}
        json_mode = response_format.get("type") == "json_object"
        json_schema = response_format.get("schema") if json_mode else None

        system_prompt, conversation_prompt = extract_system_and_conversation(messages)
        options, _ = build_sdk_options(
            cli_path=self._cli_path,
            model=model,
            model_map=_CLAUDE_MODEL_MAP,
            working_dir=kwargs.get("working_dir"),
            json_mode=json_mode,
            json_schema=json_schema,
            thinking_level=kwargs.get("thinking_level"),
            system_prompt=system_prompt,
        )

        @with_retry
        async def _do_complete() -> CompletionResult:
            from claude_agent_sdk import query
            from claude_agent_sdk.types import AssistantMessage, ResultMessage

            content_parts: list[str] = []
            thinking_parts: list[str] = []
            structured_output = None
            usage: dict[str, Any] | None = None
            cache_metrics: CacheMetrics | None = None

            async with asyncio.timeout(300.0), _sdk_semaphore:
                async for message in query(prompt=conversation_prompt, options=options):
                    if isinstance(message, ResultMessage):
                        if message.usage:
                            usage = message.usage
                        if cache_metrics is None:
                            cache_metrics = _extract_cache_metrics(message)
                        continue

                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            extracted = extract_block_content(block)
                            if extracted["type"] == "text":
                                content_parts.append(extracted["text"])
                            elif extracted["type"] == "thinking":
                                thinking_parts.append(extracted["thinking"])
                            if "structured_output" in extracted:
                                structured_output = extracted["structured_output"]

                    if hasattr(message, "structured_output") and message.structured_output and not structured_output:
                        structured_output = message.structured_output

                    if cache_metrics is None:
                        cache_metrics = _extract_cache_metrics(message)

            content = "".join(content_parts)
            thinking_content = "\n".join(thinking_parts) if thinking_parts else None

            if json_mode:
                content = (
                    json.dumps(structured_output, indent=2)
                    if structured_output
                    else extract_json_from_response(content)
                )

            input_tokens = (usage.get("input_tokens", 0) if usage else 0) or 0
            output_tokens = (usage.get("output_tokens", 0) if usage else 0) or len(content) // 4

            duration_ms = int((time.time() - start_time) * 1000)
            logger.info(
                "Claude SDK complete: %dms, %d chars, tokens=%d/%d",
                duration_ms, len(content), input_tokens, output_tokens,
            )

            return CompletionResult(
                content=content,
                model=f"claude-{sdk_model}",
                provider=self.provider_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason="end_turn",
                raw_response=None,
                cache_metrics=cache_metrics,
                thinking_content=thinking_content,
                thinking_tokens=len(thinking_content) // 4 if thinking_content else None,
            )

        try:
            return await _do_complete()
        except TimeoutError as e:
            raise ProviderError(
                "Claude SDK timeout: request exceeded 300s",
                provider=self.provider_name, retriable=True,
            ) from e
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(
                f"Claude SDK error: {e}",
                provider=self.provider_name, retriable=True,
            ) from e

    async def health_check(self) -> bool:
        """Check if Claude CLI is available."""
        return self._cli_path is not None

    async def stream(
        self,
        messages: list[Message],
        model: str,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        cache_retention: str = "none",
        **kwargs: Any,
    ) -> AsyncIterator[StreamEvent]:
        """Stream via Claude SDK query().

        When tools are passed via kwargs, they are registered as MCP servers
        so the SDK can execute them.  Tool use/result events are emitted so
        the streaming tool loop can track them without re-executing.
        """
        from claude_agent_sdk import query
        from claude_agent_sdk.types import AssistantMessage, ResultMessage

        from app.adapters.claude_utils import (
            _sdk_semaphore,
            build_sdk_options,
            extract_block_content,
            extract_system_and_conversation,
        )

        tools = kwargs.get("tools")
        working_dir = kwargs.get("working_dir", ".")
        project_id = kwargs.get("project_id")

        system_prompt, conversation_prompt = extract_system_and_conversation(messages)

        # Build MCP server if tools are provided (fixes persona tool support)
        mcp_server = _build_mcp_server(tools, working_dir, project_id) if tools else None
        mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

        options, use_streaming = build_sdk_options(
            cli_path=self._cli_path,
            model=model,
            model_map=_CLAUDE_MODEL_MAP,
            working_dir=working_dir,
            system_prompt=system_prompt,
            mcp_servers=mcp_servers,
        )

        prompt: str | Any = conversation_prompt
        if use_streaming:
            prompt = await _wrap_prompt_as_stream(conversation_prompt)

        total_content = ""
        got_done = False
        async with _sdk_semaphore:
            try:
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, ResultMessage):
                        usage = message.usage or {}
                        got_done = True
                        yield StreamEvent(
                            type="done",
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            finish_reason="end_turn",
                        )
                        return

                    content_blocks = getattr(message, "content", None)
                    if not isinstance(content_blocks, list):
                        continue

                    is_assistant = isinstance(message, AssistantMessage)
                    for block in content_blocks:
                        extracted = extract_block_content(block)
                        if extracted["type"] == "text":
                            if is_assistant:
                                total_content += extracted["text"]
                                yield StreamEvent(type="content", content=extracted["text"])
                        elif extracted["type"] == "tool_use":
                            yield StreamEvent(
                                type="tool_use",
                                tool_id=extracted["id"],
                                tool_name=extracted["name"],
                                tool_input=extracted["input"] if isinstance(extracted["input"], dict) else {},
                            )
                        elif extracted["type"] == "tool_result":
                            yield StreamEvent(
                                type="tool_result",
                                tool_id=extracted["tool_use_id"],
                                content=extracted["content"],
                            )

                if not got_done:
                    yield StreamEvent(
                        type="done",
                        input_tokens=0,
                        output_tokens=len(total_content) // 4,
                        finish_reason="end_turn",
                    )

            except asyncio.CancelledError:
                logger.warning("Claude SDK stream cancelled (cancel scope); emitting fallback done")
                if not got_done:
                    yield StreamEvent(
                        type="done",
                        input_tokens=0,
                        output_tokens=len(total_content) // 4,
                        finish_reason="end_turn",
                    )

            except TimeoutError:
                logger.error("Claude SDK stream timeout: request exceeded 300s")
                yield StreamEvent(type="error", error="Request timeout exceeded 300s")
                if not got_done:
                    yield StreamEvent(
                        type="done",
                        input_tokens=0,
                        output_tokens=len(total_content) // 4,
                        finish_reason="end_turn",
                    )

            except Exception as e:
                logger.error("Claude SDK stream error: %s", e)
                yield StreamEvent(type="error", error=str(e))
                if not got_done:
                    yield StreamEvent(
                        type="done",
                        input_tokens=0,
                        output_tokens=len(total_content) // 4,
                        finish_reason="end_turn",
                    )

    async def complete_with_tools(
        self,
        messages: list[Message],
        model: str,
        tools: list[dict[str, Any]],
        permission_config: dict[str, Any] | None = None,
        working_dir: str | None = None,
        resume_session_id: str | None = None,
        max_turns: int | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[tuple[Any, str | None]]:
        """Agentic tool execution via SDK with MCP-backed tools.

        Yields (sdk_message, session_id) tuples.
        """
        from claude_agent_sdk import query

        from app.adapters.claude_utils import (
            _sdk_semaphore,
            build_permission_checker,
            build_sdk_options,
            extract_system_and_conversation,
        )

        system_prompt, conversation_prompt = extract_system_and_conversation(messages)

        checker, yolo_mode = build_permission_checker(permission_config)
        can_use_tool_cb = _build_can_use_tool(checker) if checker and not yolo_mode else None

        mcp_server = _build_mcp_server(tools, working_dir, kwargs.get("project_id")) if tools else None
        mcp_servers = {"agent-hub": mcp_server} if mcp_server else None

        options, use_streaming = build_sdk_options(
            cli_path=self._cli_path,
            model=model,
            model_map=_CLAUDE_MODEL_MAP,
            working_dir=working_dir,
            yolo_mode=yolo_mode,
            can_use_tool=can_use_tool_cb,
            mcp_servers=mcp_servers,
            resume_session_id=resume_session_id,
            max_turns=max_turns,
            system_prompt=system_prompt,
        )

        prompt: str | Any = conversation_prompt
        if use_streaming:
            prompt = await _wrap_prompt_as_stream(conversation_prompt)

        session_id: str | None = None
        async with _sdk_semaphore:
            try:
                async for message in query(prompt=prompt, options=options):
                    if hasattr(message, "subtype") and message.subtype == "init" and hasattr(message, "data"):
                        session_id = message.data.get("session_id")  # type: ignore[union-attr]
                        if session_id:
                            logger.info("Claude SDK session ID: %s", session_id)
                    yield (message, session_id)
            except Exception as e:
                logger.error("Claude tool error: %s", e)
                raise ProviderError(
                    f"Claude tool error: {e}", provider=self.provider_name, retriable=True,
                ) from e


def _extract_cache_metrics(msg: Any) -> CacheMetrics | None:
    """Extract cache metrics from an SDK message's usage data."""
    usage = getattr(msg, "usage", None)
    if not usage:
        return None
    if isinstance(usage, dict):
        creation = usage.get("cache_creation_input_tokens", 0) or 0
        read = usage.get("cache_read_input_tokens", 0) or 0
    else:
        creation = getattr(usage, "cache_creation_input_tokens", 0) or 0
        read = getattr(usage, "cache_read_input_tokens", 0) or 0
    if creation or read:
        return CacheMetrics(cache_creation_input_tokens=creation, cache_read_input_tokens=read)
    return None
