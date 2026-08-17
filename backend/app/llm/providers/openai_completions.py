"""OpenAI Chat Completions provider — port of pi-mono ``openai-completions.ts``.

Single-file provider serving every OpenAI-compatible API the catalog uses:
OpenAI, xAI, OpenRouter, Kimi, Moonshot, DeepSeek, Zhipu, Cerebras,
Together, Nvidia, Vercel AI Gateway, GitHub Copilot, …
They differ only by ``base_url`` + (optional) ``compat`` overrides.
The 13+ legacy adapter files in ``backend/app/adapters/`` collapse into this
one module.

Reasoning across formats — openai, openrouter, deepseek, together, zai,
qwen, qwen-chat-template — is dispatched off ``compat.thinking_format``.
Tool-call IDs are normalized per provider (openai: ≤40 char; pipe-style
IDs from openai-codex/copilot: extract call_id prefix). Anthropic-style
``cache_control`` markers are applied when ``compat.cache_control_format
== "anthropic"`` (OpenRouter Anthropic models).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Literal

from openai import AsyncOpenAI
from openai._exceptions import OpenAIError

from ..api_registry import register_api_provider
from ..env_api_keys import get_env_api_key
from ..event_stream import AssistantMessageEventStream
from ..simple_options import build_base_options
from ..transform_messages import transform_messages
from ..types import (
    AssistantMessage,
    CacheRetention,
    Context,
    DoneEvent,
    ErrorEvent,
    ImageContent,
    Message,
    Model,
    OpenAICompletionsCompat,
    SimpleStreamOptions,
    StartEvent,
    StopReason,
    StreamOptions,
    TextContent,
    TextDeltaEvent,
    TextEndEvent,
    TextStartEvent,
    ThinkingContent,
    ThinkingDeltaEvent,
    ThinkingEndEvent,
    ThinkingStartEvent,
    Tool,
    ToolCall,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultMessage,
    Usage,
    UsageCost,
    UserMessage,
)
from ..utils.json_parse import parse_streaming_json
from ..utils.sanitize_unicode import sanitize_surrogates

__all__ = [
    "OpenAICompletionsOptions",
    "openai_completions_provider",
    "stream_openai_completions",
    "stream_simple_openai_completions",
]

logger = logging.getLogger(__name__)


ToolChoice = str | dict[str, Any]
ReasoningEffort = Literal["minimal", "low", "medium", "high", "xhigh"]


@dataclass(slots=True)
class OpenAICompletionsOptions(StreamOptions):
    tool_choice: ToolChoice | None = None
    reasoning_effort: ReasoningEffort | None = None


# ---------------------------------------------------------------------------
# Cache retention helpers
# ---------------------------------------------------------------------------


def _resolve_cache_retention(cache_retention: CacheRetention | None) -> CacheRetention:
    if cache_retention is not None:
        return cache_retention
    if os.environ.get("PI_CACHE_RETENTION") == "long":
        return "long"
    return "short"


@dataclass(slots=True)
class _CacheControl:
    type: Literal["ephemeral"] = "ephemeral"
    ttl: Literal["1h"] | None = None

    def to_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {"type": self.type}
        if self.ttl:
            out["ttl"] = self.ttl
        return out


# ---------------------------------------------------------------------------
# Resolved compat (defaults + auto-detection + explicit overrides)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _Compat:
    supports_store: bool = True
    supports_developer_role: bool = True
    supports_reasoning_effort: bool = True
    supports_usage_in_streaming: bool = True
    max_tokens_field: Literal["max_completion_tokens", "max_tokens"] = "max_completion_tokens"
    requires_tool_result_name: bool = False
    requires_assistant_after_tool_result: bool = False
    requires_thinking_as_text: bool = False
    requires_reasoning_content_on_assistant_messages: bool = False
    thinking_format: Literal[
        "openai", "openrouter", "deepseek", "together", "zai", "qwen", "qwen-chat-template"
    ] = "openai"
    open_router_routing: dict[str, Any] = field(default_factory=dict)
    vercel_gateway_routing: dict[str, Any] = field(default_factory=dict)
    zai_tool_stream: bool = False
    supports_strict_mode: bool = True
    cache_control_format: Literal["anthropic"] | None = None
    send_session_affinity_headers: bool = False
    supports_long_cache_retention: bool = True
    # Endpoints that reason by DEFAULT, so silence has to be requested explicitly.
    # Ollama serves several models (gemma4, qwen3, …) with thinking on unless the
    # caller opts out; the reasoning tokens consume max_tokens and the response
    # comes back 200 OK with an EMPTY content string. See _reasoning_params.
    reasons_by_default: bool = False


def _detect_compat(model: Model[Any]) -> _Compat:
    provider = model.provider
    base_url = model.base_url or ""

    is_zai = provider == "zai" or "api.z.ai" in base_url
    is_together = (
        provider == "together"
        or "api.together.ai" in base_url
        or "api.together.xyz" in base_url
    )
    is_moonshot = (
        provider in ("moonshotai", "moonshotai-cn") or "api.moonshot." in base_url
    )
    is_cf_workers = provider == "cloudflare-workers-ai" or "api.cloudflare.com" in base_url
    is_cf_gateway = provider == "cloudflare-ai-gateway" or "gateway.ai.cloudflare.com" in base_url
    is_minimax = provider == "minimax" or "api.minimax.io" in base_url
    is_ollama = provider == "local" or ":11434" in base_url

    is_non_standard = (
        provider == "cerebras"
        or "cerebras.ai" in base_url
        or is_minimax
        or provider == "xai"
        or "api.x.ai" in base_url
        or is_together
        or "chutes.ai" in base_url
        or "deepseek.com" in base_url
        or is_zai
        or is_moonshot
        or provider == "opencode"
        or "opencode.ai" in base_url
        or is_cf_workers
        or is_cf_gateway
    )

    use_max_tokens = (
        "chutes.ai" in base_url or is_minimax or is_moonshot or is_cf_gateway or is_together
    )
    is_grok = provider == "xai" or "api.x.ai" in base_url
    is_deepseek = provider == "deepseek" or "deepseek.com" in base_url

    cache_control_format: Literal["anthropic"] | None = (
        "anthropic" if provider == "openrouter" and model.id.startswith("anthropic/") else None
    )

    thinking_format: Literal[
        "openai", "openrouter", "deepseek", "together", "zai", "qwen", "qwen-chat-template"
    ]
    if is_deepseek:
        thinking_format = "deepseek"
    elif is_zai:
        thinking_format = "zai"
    elif is_together:
        thinking_format = "together"
    elif provider == "openrouter" or "openrouter.ai" in base_url:
        thinking_format = "openrouter"
    else:
        thinking_format = "openai"

    return _Compat(
        supports_store=not is_non_standard,
        supports_developer_role=not is_non_standard,
        supports_reasoning_effort=not (is_minimax or is_grok or is_zai or is_moonshot or is_together or is_cf_gateway),
        supports_usage_in_streaming=not is_minimax,
        max_tokens_field=("max_tokens" if use_max_tokens else "max_completion_tokens"),
        requires_tool_result_name=False,
        requires_assistant_after_tool_result=False,
        requires_thinking_as_text=False,
        requires_reasoning_content_on_assistant_messages=is_deepseek,
        thinking_format=thinking_format,
        zai_tool_stream=False,
        supports_strict_mode=not (is_moonshot or is_together or is_cf_gateway),
        cache_control_format=cache_control_format,
        send_session_affinity_headers=False,
        supports_long_cache_retention=not (is_together or is_cf_workers or is_cf_gateway),
        reasons_by_default=is_ollama,
    )


def _get_compat(model: Model[Any]) -> _Compat:
    detected = _detect_compat(model)
    if not isinstance(model.compat, OpenAICompletionsCompat):
        return detected

    user = model.compat

    def pick(value: Any, default: Any) -> Any:
        return value if value is not None else default

    return _Compat(
        supports_store=pick(user.supports_store, detected.supports_store),
        supports_developer_role=pick(user.supports_developer_role, detected.supports_developer_role),
        supports_reasoning_effort=pick(user.supports_reasoning_effort, detected.supports_reasoning_effort),
        supports_usage_in_streaming=pick(user.supports_usage_in_streaming, detected.supports_usage_in_streaming),
        max_tokens_field=pick(user.max_tokens_field, detected.max_tokens_field),
        requires_tool_result_name=pick(user.requires_tool_result_name, detected.requires_tool_result_name),
        requires_assistant_after_tool_result=pick(
            user.requires_assistant_after_tool_result, detected.requires_assistant_after_tool_result
        ),
        requires_thinking_as_text=pick(user.requires_thinking_as_text, detected.requires_thinking_as_text),
        requires_reasoning_content_on_assistant_messages=pick(
            user.requires_reasoning_content_on_assistant_messages,
            detected.requires_reasoning_content_on_assistant_messages,
        ),
        thinking_format=pick(user.thinking_format, detected.thinking_format),
        open_router_routing=detected.open_router_routing,
        vercel_gateway_routing=detected.vercel_gateway_routing,
        zai_tool_stream=pick(user.zai_tool_stream, detected.zai_tool_stream),
        supports_strict_mode=pick(user.supports_strict_mode, detected.supports_strict_mode),
        cache_control_format=pick(user.cache_control_format, detected.cache_control_format),
        send_session_affinity_headers=pick(
            user.send_session_affinity_headers, detected.send_session_affinity_headers
        ),
        supports_long_cache_retention=pick(
            user.supports_long_cache_retention, detected.supports_long_cache_retention
        ),
        reasons_by_default=detected.reasons_by_default,
    )


# ---------------------------------------------------------------------------
# Tool-call ID normalization
# ---------------------------------------------------------------------------


def _make_tool_call_id_normalizer(model: Model[Any]):
    def _normalize(id_: str, _model: Model[Any], _src: AssistantMessage) -> str:
        # Pipe-separated IDs from OpenAI Responses API: ``{call_id}|{id}``.
        if "|" in id_:
            head = id_.split("|", 1)[0]
            cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in head)
            return cleaned[:40]
        if model.provider == "openai":
            return id_[:40] if len(id_) > 40 else id_
        return id_

    return _normalize


# ---------------------------------------------------------------------------
# Tool-history detection (Anthropic via proxies needs tools= param)
# ---------------------------------------------------------------------------


def _has_tool_history(messages: list[Message]) -> bool:
    for msg in messages:
        if isinstance(msg, ToolResultMessage):
            return True
        if isinstance(msg, AssistantMessage) and any(isinstance(b, ToolCall) for b in msg.content):
            return True
    return False


# ---------------------------------------------------------------------------
# Message conversion
# ---------------------------------------------------------------------------


def convert_messages(
    model: Model[Any],
    context: Context,
    compat: _Compat,
) -> list[dict[str, Any]]:
    """Convert universal messages to OpenAI Chat Completions ``messages`` array."""

    normalize = _make_tool_call_id_normalizer(model)
    transformed = transform_messages(context.messages, model, normalize)

    params: list[dict[str, Any]] = []

    if context.system_prompt:
        role = "developer" if (model.reasoning and compat.supports_developer_role) else "system"
        params.append({"role": role, "content": sanitize_surrogates(context.system_prompt)})

    last_role: str | None = None
    i = 0
    while i < len(transformed):
        msg = transformed[i]

        # Some providers don't allow user messages directly after tool results.
        if (
            compat.requires_assistant_after_tool_result
            and last_role == "toolResult"
            and isinstance(msg, UserMessage)
        ):
            params.append({"role": "assistant", "content": "I have processed the tool results."})

        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                params.append({"role": "user", "content": sanitize_surrogates(msg.content)})
            else:
                content: list[dict[str, Any]] = []
                for item in msg.content:
                    if isinstance(item, TextContent):
                        content.append({"type": "text", "text": sanitize_surrogates(item.text)})
                    elif isinstance(item, ImageContent):
                        content.append(
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{item.mime_type};base64,{item.data}"},
                            }
                        )
                if content:
                    params.append({"role": "user", "content": content})
            last_role = "user"
            i += 1
            continue

        if isinstance(msg, AssistantMessage):
            text_parts = [
                {"type": "text", "text": sanitize_surrogates(b.text)}
                for b in msg.content
                if isinstance(b, TextContent) and b.text.strip()
            ]
            assistant_text = "".join(p["text"] for p in text_parts)
            non_empty_thinking = [
                b for b in msg.content if isinstance(b, ThinkingContent) and b.thinking.strip()
            ]
            tool_calls = [b for b in msg.content if isinstance(b, ToolCall)]

            assistant: dict[str, Any] = {"role": "assistant"}
            assistant["content"] = "" if compat.requires_assistant_after_tool_result else None

            if non_empty_thinking:
                if compat.requires_thinking_as_text:
                    thinking_text = "\n\n".join(sanitize_surrogates(b.thinking) for b in non_empty_thinking)
                    assistant["content"] = [{"type": "text", "text": thinking_text}, *text_parts]
                else:
                    if assistant_text:
                        assistant["content"] = assistant_text
                    signature = non_empty_thinking[0].thinking_signature
                    if signature:
                        assistant[signature] = "\n".join(b.thinking for b in non_empty_thinking)
            elif assistant_text:
                assistant["content"] = assistant_text

            if tool_calls:
                assistant["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
                    }
                    for tc in tool_calls
                ]
                reasoning_details = []
                for tc in tool_calls:
                    if tc.thought_signature:
                        try:
                            reasoning_details.append(json.loads(tc.thought_signature))
                        except Exception:
                            continue
                if reasoning_details:
                    assistant["reasoning_details"] = reasoning_details

            if (
                compat.requires_reasoning_content_on_assistant_messages
                and model.reasoning
                and "reasoning_content" not in assistant
            ):
                assistant["reasoning_content"] = ""

            content = assistant.get("content")
            has_content = content not in (None, "") and (not isinstance(content, list) or content)
            if not has_content and "tool_calls" not in assistant:
                i += 1
                continue

            params.append(assistant)
            last_role = "assistant"
            i += 1
            continue

        if isinstance(msg, ToolResultMessage):
            image_blocks: list[dict[str, Any]] = []
            j = i
            while j < len(transformed) and isinstance(transformed[j], ToolResultMessage):
                tool_msg = transformed[j]
                assert isinstance(tool_msg, ToolResultMessage)

                text_result = "\n".join(
                    b.text for b in tool_msg.content if isinstance(b, TextContent)
                )
                has_images = any(isinstance(c, ImageContent) for c in tool_msg.content)
                has_text = bool(text_result)
                tool_result_msg: dict[str, Any] = {
                    "role": "tool",
                    "content": sanitize_surrogates(text_result if has_text else "(see attached image)"),
                    "tool_call_id": tool_msg.tool_call_id,
                }
                if compat.requires_tool_result_name and tool_msg.tool_name:
                    tool_result_msg["name"] = tool_msg.tool_name
                params.append(tool_result_msg)

                if has_images and "image" in model.input:
                    for block in tool_msg.content:
                        if isinstance(block, ImageContent):
                            image_blocks.append(
                                {
                                    "type": "image_url",
                                    "image_url": {"url": f"data:{block.mime_type};base64,{block.data}"},
                                }
                            )
                j += 1

            i = j

            if image_blocks:
                if compat.requires_assistant_after_tool_result:
                    params.append({"role": "assistant", "content": "I have processed the tool results."})
                params.append(
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": "Attached image(s) from tool result:"},
                            *image_blocks,
                        ],
                    }
                )
                last_role = "user"
            else:
                last_role = "toolResult"
            continue

        i += 1

    return params


def _convert_tools(tools: list[Tool], compat: _Compat) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for tool in tools:
        fn: dict[str, Any] = {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
        }
        entry: dict[str, Any] = {"type": "function", "function": fn}
        if compat.supports_strict_mode:
            fn["strict"] = False
        out.append(entry)
    return out


# ---------------------------------------------------------------------------
# Anthropic-style cache_control application (OpenRouter Anthropic models)
# ---------------------------------------------------------------------------


def _get_compat_cache_control(
    compat: _Compat, cache_retention: CacheRetention
) -> _CacheControl | None:
    if compat.cache_control_format != "anthropic" or cache_retention == "none":
        return None
    ttl = "1h" if cache_retention == "long" and compat.supports_long_cache_retention else None
    return _CacheControl(ttl=ttl)


def _apply_anthropic_cache_control(
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    cache_control: _CacheControl,
) -> None:
    payload = cache_control.to_payload()
    _add_cc_to_system(messages, payload)
    _add_cc_to_last_tool(tools, payload)
    _add_cc_to_last_conversation(messages, payload)


def _add_cc_to_system(messages: list[dict[str, Any]], cc: dict[str, Any]) -> None:
    for msg in messages:
        if msg["role"] in ("system", "developer"):
            _add_cc_to_text_content(msg, cc)
            return


def _add_cc_to_last_tool(tools: list[dict[str, Any]] | None, cc: dict[str, Any]) -> None:
    if not tools:
        return
    tools[-1]["cache_control"] = cc


def _add_cc_to_last_conversation(messages: list[dict[str, Any]], cc: dict[str, Any]) -> None:
    for msg in reversed(messages):
        if msg["role"] in ("user", "assistant") and _add_cc_to_text_content(msg, cc):
            return


def _add_cc_to_text_content(msg: dict[str, Any], cc: dict[str, Any]) -> bool:
    content = msg.get("content")
    if isinstance(content, str):
        if not content:
            return False
        msg["content"] = [{"type": "text", "text": content, "cache_control": cc}]
        return True
    if isinstance(content, list):
        for i in range(len(content) - 1, -1, -1):
            part = content[i]
            if isinstance(part, dict) and part.get("type") == "text":
                part["cache_control"] = cc
                return True
    return False


# ---------------------------------------------------------------------------
# Param building
# ---------------------------------------------------------------------------


def build_params(
    model: Model[Any],
    context: Context,
    options: OpenAICompletionsOptions | None,
    compat: _Compat,
    cache_retention: CacheRetention,
) -> dict[str, Any]:
    messages = convert_messages(model, context, compat)
    cache_control = _get_compat_cache_control(compat, cache_retention)

    params: dict[str, Any] = {
        "model": model.id,
        "messages": messages,
        "stream": True,
    }

    prompt_cache_key: str | None = None
    if (
        ("api.openai.com" in (model.base_url or "") and cache_retention != "none")
        or (cache_retention == "long" and compat.supports_long_cache_retention)
    ):
        prompt_cache_key = options.session_id if options else None
    if prompt_cache_key:
        params["prompt_cache_key"] = prompt_cache_key
    if cache_retention == "long" and compat.supports_long_cache_retention:
        params["prompt_cache_retention"] = "24h"

    if compat.supports_usage_in_streaming:
        params["stream_options"] = {"include_usage": True}
    if compat.supports_store:
        params["store"] = False

    if options and options.max_tokens:
        params[compat.max_tokens_field] = options.max_tokens
    if options and options.temperature is not None:
        params["temperature"] = options.temperature

    tools_param: list[dict[str, Any]] | None = None
    if context.tools:
        tools_param = _convert_tools(context.tools, compat)
        params["tools"] = tools_param
        if compat.zai_tool_stream:
            params["tool_stream"] = True
    elif _has_tool_history(context.messages):
        params["tools"] = []
        tools_param = []

    if cache_control:
        _apply_anthropic_cache_control(messages, tools_param, cache_control)

    if options and options.tool_choice:
        params["tool_choice"] = options.tool_choice

    reasoning_effort = options.reasoning_effort if options else None

    if compat.thinking_format in ("zai", "qwen") and model.reasoning:
        params["enable_thinking"] = bool(reasoning_effort)
    elif compat.thinking_format == "qwen-chat-template" and model.reasoning:
        params["chat_template_kwargs"] = {
            "enable_thinking": bool(reasoning_effort),
            "preserve_thinking": True,
        }
    elif compat.thinking_format == "deepseek" and model.reasoning:
        params["thinking"] = {"type": "enabled" if reasoning_effort else "disabled"}
        if reasoning_effort:
            params["reasoning_effort"] = (
                (model.thinking_level_map or {}).get(reasoning_effort) or reasoning_effort
            )
    elif compat.thinking_format == "openrouter" and model.reasoning:
        if reasoning_effort:
            params["reasoning"] = {
                "effort": (model.thinking_level_map or {}).get(reasoning_effort) or reasoning_effort
            }
        elif (model.thinking_level_map or {}).get("off") is not None:
            params["reasoning"] = {"effort": (model.thinking_level_map or {}).get("off") or "none"}
    elif compat.thinking_format == "together" and model.reasoning:
        params["reasoning"] = {"enabled": bool(reasoning_effort)}
        if reasoning_effort and compat.supports_reasoning_effort:
            params["reasoning_effort"] = (
                (model.thinking_level_map or {}).get(reasoning_effort) or reasoning_effort
            )
    elif reasoning_effort and model.reasoning and compat.supports_reasoning_effort:
        params["reasoning_effort"] = (
            (model.thinking_level_map or {}).get(reasoning_effort) or reasoning_effort
        )
    elif not reasoning_effort and model.reasoning and compat.supports_reasoning_effort:
        off_value = (model.thinking_level_map or {}).get("off")
        if isinstance(off_value, str):
            params["reasoning_effort"] = off_value
    elif not model.reasoning and compat.reasons_by_default:
        # The catalog says this model does not reason, but the endpoint reasons
        # unless told otherwise. Without this the reasoning stream eats the whole
        # max_tokens budget and the caller gets content="" with no error at all —
        # which silently kills the local rung that 77 of 79 agents fall back to.
        params["reasoning_effort"] = "none"

    # OpenRouter provider routing.
    if "openrouter.ai" in (model.base_url or "") and isinstance(model.compat, OpenAICompletionsCompat) and model.compat.open_router_routing:
        params["provider"] = model.compat.open_router_routing

    # Vercel AI Gateway routing.
    if (
        "ai-gateway.vercel.sh" in (model.base_url or "")
        and isinstance(model.compat, OpenAICompletionsCompat)
        and model.compat.vercel_gateway_routing
    ):
        routing = model.compat.vercel_gateway_routing
        gateway: dict[str, Any] = {}
        if routing.only:
            gateway["only"] = routing.only
        if routing.order:
            gateway["order"] = routing.order
        if gateway:
            params["providerOptions"] = {"gateway": gateway}

    if model.provider == "local" and model.id.startswith("gemma4:"):
        from app.config import settings

        keep_alive = settings.local_gemma4_keep_alive.strip()
        if keep_alive:
            params["keep_alive"] = keep_alive

    return params


_OPENAI_CHAT_COMPLETIONS_PARAM_KEYS = {
    "audio",
    "frequency_penalty",
    "function_call",
    "functions",
    "logit_bias",
    "logprobs",
    "max_completion_tokens",
    "max_tokens",
    "messages",
    "metadata",
    "modalities",
    "model",
    "n",
    "parallel_tool_calls",
    "prediction",
    "presence_penalty",
    "prompt_cache_key",
    "prompt_cache_retention",
    "reasoning_effort",
    "response_format",
    "safety_identifier",
    "seed",
    "service_tier",
    "stop",
    "store",
    "stream_options",
    "temperature",
    "tool_choice",
    "tools",
    "top_logprobs",
    "top_p",
    "user",
    "verbosity",
    "web_search_options",
}


def _prepare_sdk_body(params: dict[str, Any]) -> dict[str, Any]:
    """Move provider-specific Chat Completions fields into ``extra_body``."""
    body: dict[str, Any] = {}
    extra_body: dict[str, Any] = {}
    for key, value in params.items():
        if key in _OPENAI_CHAT_COMPLETIONS_PARAM_KEYS:
            body[key] = value
        else:
            extra_body[key] = value
    if extra_body:
        existing = body.get("extra_body")
        if isinstance(existing, dict):
            extra_body = {**existing, **extra_body}
        body["extra_body"] = extra_body
    return body


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


def create_client(
    model: Model[Any],
    api_key: str,
    options_headers: dict[str, str] | None,
    session_id: str | None,
    compat: _Compat,
) -> AsyncOpenAI:
    headers: dict[str, str] = dict(model.headers or {})
    if session_id and compat.send_session_affinity_headers:
        headers["session_id"] = session_id
        headers["x-client-request-id"] = session_id
        headers["x-session-affinity"] = session_id
    if options_headers:
        headers.update(options_headers)

    if model.provider == "cloudflare-ai-gateway":
        headers["cf-aig-authorization"] = f"Bearer {api_key}"

    return AsyncOpenAI(
        api_key=api_key or "placeholder",
        base_url=model.base_url,
        default_headers=headers,
    )


# ---------------------------------------------------------------------------
# Usage / cost / stop reason
# ---------------------------------------------------------------------------


def _calculate_cost(model: Model[Any], usage: Usage) -> None:
    cost = model.cost
    usage.cost = UsageCost(
        input=usage.input * cost.input / 1_000_000,
        output=usage.output * cost.output / 1_000_000,
        cache_read=usage.cache_read * cost.cache_read / 1_000_000,
        cache_write=usage.cache_write * cost.cache_write / 1_000_000,
    )
    usage.cost.total = (
        usage.cost.input + usage.cost.output + usage.cost.cache_read + usage.cost.cache_write
    )


def _parse_chunk_usage(raw: Any, model: Model[Any]) -> Usage:
    prompt_tokens = int(getattr(raw, "prompt_tokens", 0) or 0)
    details = getattr(raw, "prompt_tokens_details", None) or {}
    if hasattr(details, "cached_tokens"):
        reported_cached = int(getattr(details, "cached_tokens", 0) or 0)
        cache_write = int(getattr(details, "cache_write_tokens", 0) or 0)
    elif isinstance(details, dict):
        reported_cached = int(details.get("cached_tokens", 0) or 0)
        cache_write = int(details.get("cache_write_tokens", 0) or 0)
    else:
        reported_cached = int(getattr(raw, "prompt_cache_hit_tokens", 0) or 0)
        cache_write = 0

    cache_read = max(0, reported_cached - cache_write) if cache_write > 0 else reported_cached
    input_tokens = max(0, prompt_tokens - cache_read - cache_write)
    output_tokens = int(getattr(raw, "completion_tokens", 0) or 0)

    usage = Usage(
        input=input_tokens,
        output=output_tokens,
        cache_read=cache_read,
        cache_write=cache_write,
        total_tokens=input_tokens + output_tokens + cache_read + cache_write,
    )
    _calculate_cost(model, usage)
    return usage


def _map_stop_reason(reason: str | None) -> tuple[StopReason, str | None]:
    if reason is None:
        return "stop", None
    if reason in ("stop", "end"):
        return "stop", None
    if reason == "length":
        return "length", None
    if reason in ("function_call", "tool_calls"):
        return "toolUse", None
    if reason == "content_filter":
        return "error", "Provider finish_reason: content_filter"
    if reason == "network_error":
        return "error", "Provider finish_reason: network_error"
    return "error", f"Provider finish_reason: {reason}"


# ---------------------------------------------------------------------------
# Streaming state scratch
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _ToolCallScratch:
    block: ToolCall
    content_index: int
    stream_index: int | None = None
    partial_args: str = ""


@dataclass(slots=True)
class _StreamState:
    output: AssistantMessage
    text_block: TextContent | None = None
    text_content_index: int | None = None
    thinking_block: ThinkingContent | None = None
    thinking_content_index: int | None = None
    by_index: dict[int, _ToolCallScratch] = field(default_factory=dict)
    by_id: dict[str, _ToolCallScratch] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Streaming entry point
# ---------------------------------------------------------------------------


_REASONING_FIELDS = ("reasoning_content", "reasoning", "reasoning_text")


def stream_openai_completions(
    model: Model[Any],
    context: Context,
    options: OpenAICompletionsOptions | None = None,
) -> AssistantMessageEventStream:
    stream = AssistantMessageEventStream()

    async def runner() -> None:
        output = AssistantMessage(
            content=[],
            api=model.api,
            provider=model.provider,
            model=model.id,
            usage=Usage(),
            stop_reason="stop",
            timestamp=int(time.time() * 1000),
        )
        state = _StreamState(output=output)

        try:
            compat = _get_compat(model)
            cache_retention = _resolve_cache_retention(
                options.cache_retention if options else None
            )
            api_key = (options.api_key if options else None) or get_env_api_key(model.provider) or ""
            client = create_client(
                model,
                api_key,
                options.headers if options else None,
                options.session_id if options and cache_retention != "none" else None,
                compat,
            )

            params = build_params(model, context, options, compat, cache_retention)
            if options and options.on_payload is not None:
                maybe = options.on_payload(params, model)
                if asyncio.iscoroutine(maybe):
                    maybe = await maybe
                if maybe is not None and isinstance(maybe, dict):
                    params = maybe

            request_options: dict[str, Any] = {}
            if options and options.timeout_ms is not None:
                request_options["timeout"] = options.timeout_ms / 1000

            body = dict(params)
            body.pop("stream", None)
            body = _prepare_sdk_body(body)
            iterator = await client.chat.completions.create(stream=True, **body, **request_options)

            stream.push(StartEvent(partial=output))

            async for chunk in iterator:
                if options and options.signal is not None and options.signal.is_set():
                    raise asyncio.CancelledError("Request was aborted")

                if chunk is None:
                    continue

                chunk_id = getattr(chunk, "id", None)
                if chunk_id and not output.response_id:
                    output.response_id = chunk_id
                chunk_model = getattr(chunk, "model", None)
                if (
                    isinstance(chunk_model, str)
                    and chunk_model
                    and chunk_model != model.id
                    and not output.response_model
                ):
                    output.response_model = chunk_model

                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    output.usage = _parse_chunk_usage(usage, model)

                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                choice = choices[0]

                choice_usage = getattr(choice, "usage", None)
                if usage is None and choice_usage is not None:
                    output.usage = _parse_chunk_usage(choice_usage, model)

                finish_reason = getattr(choice, "finish_reason", None)
                if finish_reason:
                    sr, err = _map_stop_reason(finish_reason)
                    output.stop_reason = sr
                    if err:
                        output.error_message = err

                delta = getattr(choice, "delta", None)
                if delta is None:
                    continue

                # Text content.
                content = getattr(delta, "content", None)
                if content:
                    if state.text_block is None:
                        state.text_block = TextContent(text="")
                        output.content.append(state.text_block)
                        state.text_content_index = len(output.content) - 1
                        stream.push(
                            TextStartEvent(content_index=state.text_content_index, partial=output)
                        )
                    state.text_block.text += content
                    assert state.text_content_index is not None
                    stream.push(
                        TextDeltaEvent(
                            content_index=state.text_content_index,
                            delta=content,
                            partial=output,
                        )
                    )

                # Reasoning content (multiple legacy field names).
                reasoning_value: str | None = None
                reasoning_field: str | None = None
                for fld in _REASONING_FIELDS:
                    value = getattr(delta, fld, None)
                    if value is None and isinstance(delta, dict):
                        value = delta.get(fld)
                    if isinstance(value, str) and value:
                        reasoning_value = value
                        reasoning_field = fld
                        break
                if reasoning_value:
                    if state.thinking_block is None:
                        state.thinking_block = ThinkingContent(
                            thinking="", thinking_signature=reasoning_field
                        )
                        output.content.append(state.thinking_block)
                        state.thinking_content_index = len(output.content) - 1
                        stream.push(
                            ThinkingStartEvent(
                                content_index=state.thinking_content_index, partial=output
                            )
                        )
                    state.thinking_block.thinking += reasoning_value
                    assert state.thinking_content_index is not None
                    stream.push(
                        ThinkingDeltaEvent(
                            content_index=state.thinking_content_index,
                            delta=reasoning_value,
                            partial=output,
                        )
                    )

                # Tool calls.
                tool_calls = getattr(delta, "tool_calls", None) or []
                for tc in tool_calls:
                    scratch = _ensure_tool_call_scratch(state, output, stream, tc)
                    new_id = getattr(tc, "id", None)
                    if new_id and not scratch.block.id:
                        scratch.block.id = new_id
                        state.by_id[new_id] = scratch
                    fn = getattr(tc, "function", None)
                    if fn is not None:
                        new_name = getattr(fn, "name", None)
                        if new_name and not scratch.block.name:
                            scratch.block.name = new_name
                        new_args = getattr(fn, "arguments", None)
                        if new_args:
                            scratch.partial_args += new_args
                            scratch.block.arguments = parse_streaming_json(scratch.partial_args)
                            stream.push(
                                ToolCallDeltaEvent(
                                    content_index=scratch.content_index,
                                    delta=new_args,
                                    partial=output,
                                )
                            )

                # Reasoning details for thoughtSignature (OpenRouter etc.).
                reasoning_details = getattr(delta, "reasoning_details", None)
                if reasoning_details is None and isinstance(delta, dict):
                    reasoning_details = delta.get("reasoning_details")
                if isinstance(reasoning_details, list):
                    for detail in reasoning_details:
                        if (
                            isinstance(detail, dict)
                            and detail.get("type") == "reasoning.encrypted"
                            and detail.get("id")
                            and detail.get("data")
                        ):
                            for b in output.content:
                                if isinstance(b, ToolCall) and b.id == detail["id"]:
                                    b.thought_signature = json.dumps(detail)

            # Finalize any open blocks.
            if state.text_block is not None and state.text_content_index is not None:
                stream.push(
                    TextEndEvent(
                        content_index=state.text_content_index,
                        content=state.text_block.text,
                        partial=output,
                    )
                )
            if state.thinking_block is not None and state.thinking_content_index is not None:
                stream.push(
                    ThinkingEndEvent(
                        content_index=state.thinking_content_index,
                        content=state.thinking_block.thinking,
                        partial=output,
                    )
                )
            for scratch in state.by_index.values():
                scratch.block.arguments = parse_streaming_json(scratch.partial_args)
                stream.push(
                    ToolCallEndEvent(
                        content_index=scratch.content_index,
                        tool_call=scratch.block,
                        partial=output,
                    )
                )

            if options and options.signal is not None and options.signal.is_set():
                raise asyncio.CancelledError("Request was aborted")
            if output.stop_reason == "error":
                raise RuntimeError(output.error_message or "Provider returned an error stop reason")
            if output.stop_reason == "aborted":
                raise RuntimeError("Request was aborted")

            done_reason = output.stop_reason if output.stop_reason in ("stop", "length", "toolUse") else "stop"
            stream.push(DoneEvent(reason=done_reason, message=output))
            stream.end()
        except asyncio.CancelledError as exc:
            output.stop_reason = "aborted"
            output.error_message = str(exc) or "Request was aborted"
            stream.push(ErrorEvent(reason="aborted", error=output))
            stream.end()
        except (OpenAIError, Exception) as exc:
            aborted = bool(options and options.signal is not None and options.signal.is_set())
            output.stop_reason = "aborted" if aborted else "error"
            output.error_message = str(exc) or type(exc).__name__
            stream.push(ErrorEvent(reason=("aborted" if aborted else "error"), error=output))
            stream.end()

    runner_task = asyncio.create_task(runner())
    stream._oai_runner_task = runner_task  # type: ignore[attr-defined]
    return stream


def _ensure_tool_call_scratch(
    state: _StreamState,
    output: AssistantMessage,
    stream: AssistantMessageEventStream,
    tc: Any,
) -> _ToolCallScratch:
    stream_index = getattr(tc, "index", None)
    if not isinstance(stream_index, int):
        stream_index = None

    scratch: _ToolCallScratch | None = None
    if stream_index is not None:
        scratch = state.by_index.get(stream_index)
    if scratch is None:
        tc_id = getattr(tc, "id", None)
        if tc_id:
            scratch = state.by_id.get(tc_id)

    if scratch is None:
        fn = getattr(tc, "function", None)
        tc_id = getattr(tc, "id", "") or ""
        name = getattr(fn, "name", "") if fn else ""
        block = ToolCall(id=tc_id, name=name or "", arguments={})
        output.content.append(block)
        content_index = len(output.content) - 1
        scratch = _ToolCallScratch(
            block=block,
            content_index=content_index,
            stream_index=stream_index,
        )
        if stream_index is not None:
            state.by_index[stream_index] = scratch
        if tc_id:
            state.by_id[tc_id] = scratch
        stream.push(ToolCallStartEvent(content_index=content_index, partial=output))
    elif stream_index is not None and scratch.stream_index is None:
        scratch.stream_index = stream_index
        state.by_index[stream_index] = scratch

    return scratch


def stream_simple_openai_completions(
    model: Model[Any],
    context: Context,
    options: SimpleStreamOptions | None = None,
) -> AssistantMessageEventStream:
    if options is None:
        options = SimpleStreamOptions()
    api_key = options.api_key or get_env_api_key(model.provider)
    if not api_key:
        raise RuntimeError(f"No API key for provider: {model.provider}")

    base = build_base_options(model, options, api_key)
    reasoning_effort = options.reasoning if options.reasoning else None

    return stream_openai_completions(
        model,
        context,
        OpenAICompletionsOptions(
            temperature=base.temperature,
            max_tokens=base.max_tokens,
            signal=base.signal,
            api_key=base.api_key,
            transport=base.transport,
            cache_retention=base.cache_retention,
            session_id=base.session_id,
            on_payload=base.on_payload,
            on_response=base.on_response,
            headers=base.headers,
            timeout_ms=base.timeout_ms,
            max_retries=base.max_retries,
            max_retry_delay_ms=base.max_retry_delay_ms,
            metadata=base.metadata,
            reasoning_effort=reasoning_effort,
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


class _OpenAICompletionsProvider:
    api: str = "openai-completions"

    def stream(
        self,
        model: Model[Any],
        context: Context,
        options: StreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        if isinstance(options, OpenAICompletionsOptions):
            return stream_openai_completions(model, context, options)
        if options is None:
            return stream_openai_completions(model, context, None)
        return stream_openai_completions(
            model,
            context,
            OpenAICompletionsOptions(
                temperature=options.temperature,
                max_tokens=options.max_tokens,
                signal=options.signal,
                api_key=options.api_key,
                transport=options.transport,
                cache_retention=options.cache_retention,
                session_id=options.session_id,
                on_payload=options.on_payload,
                on_response=options.on_response,
                headers=options.headers,
                timeout_ms=options.timeout_ms,
                max_retries=options.max_retries,
                max_retry_delay_ms=options.max_retry_delay_ms,
                metadata=options.metadata,
            ),
        )

    def stream_simple(
        self,
        model: Model[Any],
        context: Context,
        options: SimpleStreamOptions | None = None,
    ) -> AssistantMessageEventStream:
        return stream_simple_openai_completions(model, context, options)


openai_completions_provider = _OpenAICompletionsProvider()

register_api_provider(openai_completions_provider)
