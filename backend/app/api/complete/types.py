"""Type definitions for completion API."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from app.llm.types import (
    AssistantMessage,
    TextContent,
    ThinkingContent,
    ToolCall,
    Usage,
)
from app.services.llm_messages import CacheMetrics, ToolCallResult

from .progress import AgentProgress


@dataclass(init=False)
class CompletionInternalResult:
    """HTTP completion metadata around the universal assistant message."""

    message: AssistantMessage
    session_id: str
    memory_uuids: list[str]
    cited_uuids: list[str]
    cache_hit: bool = False
    runtime_cache: Any | None = None
    reasoning_text: str | None = None
    reasoning_token_count: int | None = None
    tool_call_results: list[Any] | None = None
    container_state: Any | None = None
    # Multi-turn execution fields
    turn_count: int = 1
    executed_tool_call_count: int = 0
    execution_status: str = "success"
    execution_error: str | None = None
    container_ref: str | None = None
    progress_entries: list[AgentProgress] = field(default_factory=list)
    failure_summary: dict[str, Any] | None = None
    # Headroom tool-result compression aggregate for this request (None when off).
    compression_stats: dict[str, int] | None = None
    # Fallback tracking
    model_used: str | None = None
    fallback_used: bool = False
    requested_model: str | None = None
    requested_provider: str | None = None
    fallback_reason: str | None = None

    def __init__(
        self,
        *,
        message: AssistantMessage | None = None,
        content: str = "",
        model: str = "unknown",
        provider: str = "unknown",
        input_tokens: int = 0,
        output_tokens: int = 0,
        finish_reason: str | None = "stop",
        session_id: str = "",
        memory_uuids: list[str] | None = None,
        cited_uuids: list[str] | None = None,
        from_cache: bool = False,
        cache_metrics: Any | None = None,
        thinking_content: str | None = None,
        thinking_tokens: int | None = None,
        tool_calls: list[Any] | None = None,
        container: Any | None = None,
        turns: int = 1,
        tool_calls_count: int = 0,
        status: str = "success",
        error: str | None = None,
        container_id: str | None = None,
        progress_log: list[AgentProgress] | None = None,
        error_summary: dict[str, Any] | None = None,
        compression_stats: dict[str, int] | None = None,
        model_used: str | None = None,
        fallback_used: bool = False,
        requested_model: str | None = None,
        requested_provider: str | None = None,
        fallback_reason: str | None = None,
    ) -> None:
        if message is None:
            message = self._message_from_flat_fields(
                content=content,
                model=model,
                provider=provider,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                finish_reason=finish_reason,
                thinking_content=thinking_content,
                tool_calls=tool_calls,
            )
        self.message = message
        self.session_id = session_id
        self.memory_uuids = memory_uuids or []
        self.cited_uuids = cited_uuids or []
        self.cache_hit = from_cache
        self.runtime_cache = cache_metrics
        self.reasoning_text = thinking_content
        self.reasoning_token_count = thinking_tokens
        self.tool_call_results = tool_calls
        self.container_state = container
        self.turn_count = turns
        self.executed_tool_call_count = tool_calls_count
        self.execution_status = status
        self.execution_error = error
        self.container_ref = container_id
        self.progress_entries = progress_log or []
        self.failure_summary = error_summary
        self.compression_stats = compression_stats
        self.model_used = model_used
        self.fallback_used = fallback_used
        self.requested_model = requested_model
        self.requested_provider = requested_provider
        self.fallback_reason = fallback_reason
        self._finish_reason = finish_reason

    @staticmethod
    def _message_from_flat_fields(
        *,
        content: str,
        model: str,
        provider: str,
        input_tokens: int,
        output_tokens: int,
        finish_reason: str | None,
        thinking_content: str | None,
        tool_calls: list[Any] | None,
    ) -> AssistantMessage:
        blocks: list[Any] = []
        if thinking_content:
            blocks.append(ThinkingContent(thinking=thinking_content))
        if content:
            blocks.append(TextContent(text=content))
        for raw_tool_call in tool_calls or []:
            if isinstance(raw_tool_call, ToolCall):
                blocks.append(raw_tool_call)
                continue
            if isinstance(raw_tool_call, dict):
                arguments = raw_tool_call.get("arguments", raw_tool_call.get("input", {}))
                blocks.append(
                    ToolCall(
                        id=str(raw_tool_call.get("id", "")),
                        name=str(raw_tool_call.get("name", "")),
                        arguments=arguments if isinstance(arguments, dict) else {},
                    )
                )
        return AssistantMessage(
            content=blocks,
            api=provider,
            provider=provider,
            model=model,
            usage=Usage(
                input=input_tokens,
                output=output_tokens,
                total_tokens=input_tokens + output_tokens,
            ),
            stop_reason=_to_stop_reason(finish_reason),
            timestamp=int(time.time() * 1000),
        )

    @property
    def content(self) -> str:
        text = "".join(
            block.text for block in self.message.content if isinstance(block, TextContent)
        )
        if any(isinstance(block, ThinkingContent) for block in self.message.content):
            return text.strip()
        return text

    @property
    def model(self) -> str:
        return self.requested_model or self.message.model

    @property
    def provider(self) -> str:
        return self.requested_provider or self.message.provider

    @property
    def input_tokens(self) -> int:
        return self.message.usage.input

    @property
    def output_tokens(self) -> int:
        return self.message.usage.output

    @property
    def finish_reason(self) -> str | None:
        return self._finish_reason or self.message.stop_reason

    @property
    def cache_metrics(self) -> Any | None:
        if self.runtime_cache is not None:
            return self.runtime_cache
        if self.message.usage.cache_read or self.message.usage.cache_write:
            return CacheMetrics(
                cache_creation_input_tokens=self.message.usage.cache_write,
                cache_read_input_tokens=self.message.usage.cache_read,
            )
        return None

    @property
    def from_cache(self) -> bool:
        return self.cache_hit

    @from_cache.setter
    def from_cache(self, value: bool) -> None:
        self.cache_hit = value

    @property
    def status(self) -> str:
        return self.execution_status

    @status.setter
    def status(self, value: str) -> None:
        self.execution_status = value

    @property
    def error(self) -> str | None:
        return self.execution_error

    @error.setter
    def error(self, value: str | None) -> None:
        self.execution_error = value

    @property
    def progress_log(self) -> list[AgentProgress]:
        return self.progress_entries

    @progress_log.setter
    def progress_log(self, value: list[AgentProgress]) -> None:
        self.progress_entries = value

    @property
    def error_summary(self) -> dict[str, Any] | None:
        return self.failure_summary

    @error_summary.setter
    def error_summary(self, value: dict[str, Any] | None) -> None:
        self.failure_summary = value

    @property
    def thinking_content(self) -> str | None:
        if self.reasoning_text is not None:
            return self.reasoning_text
        text = "".join(
            block.thinking
            for block in self.message.content
            if isinstance(block, ThinkingContent) and not block.redacted
        )
        return text or None

    @property
    def thinking_tokens(self) -> int | None:
        return self.reasoning_token_count

    @property
    def tool_calls(self) -> list[Any] | None:
        if self.tool_call_results is not None:
            return self.tool_call_results
        calls = [
            ToolCallResult(id=block.id, name=block.name, input=block.arguments)
            for block in self.message.content
            if isinstance(block, ToolCall)
        ]
        return calls or None

    @property
    def container(self) -> Any | None:
        return self.container_state

    @property
    def container_id(self) -> str | None:
        return self.container_ref

    @container_id.setter
    def container_id(self, value: str | None) -> None:
        self.container_ref = value

    @property
    def turns(self) -> int:
        return self.turn_count

    @turns.setter
    def turns(self, value: int) -> None:
        self.turn_count = value

    @property
    def tool_calls_count(self) -> int:
        return self.executed_tool_call_count

    @tool_calls_count.setter
    def tool_calls_count(self, value: int) -> None:
        self.executed_tool_call_count = value


def _to_stop_reason(reason: str | None) -> str:
    if reason in {"stop", "length", "toolUse", "error", "aborted"}:
        return reason
    if reason in {"tool_use", "tool_calls"}:
        return "toolUse"
    if reason in {"max_tokens", "max_turns"}:
        return "length"
    return "stop"
