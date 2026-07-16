"""Shared utilities for Google Generative AI + (eventual) Vertex providers.

Direct port of pi-mono ``providers/google-shared.ts``. Used by
``google.py``; if a Phase 2 catalog entry needs Vertex, a
``google_vertex.py`` will share these helpers too.
"""

from __future__ import annotations

import re
from typing import Any

from ..transform_messages import transform_messages
from ..types import (
    AssistantMessage,
    AudioContent,
    Context,
    ImageContent,
    Model,
    StopReason,
    TextContent,
    ThinkingContent,
    Tool,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from ..utils.sanitize_unicode import sanitize_surrogates

# Gemini's ``ThinkingLevel`` enum values, used for Gemini 3 family models.
GoogleThinkingLevel = str  # one of THINKING_LEVEL_UNSPECIFIED|MINIMAL|LOW|MEDIUM|HIGH


_BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]+={0,2}$")


def is_thinking_part(part: dict[str, Any]) -> bool:
    """``thought: true`` is the only definitive thinking marker."""
    return part.get("thought") is True


def retain_thought_signature(existing: str | None, incoming: str | None) -> str | None:
    """Preserve the last non-empty signature for the current streaming block.

    Some backends only send ``thoughtSignature`` on the first delta. Don't
    let later deltas overwrite it with ``None``.
    """

    if isinstance(incoming, str) and incoming:
        return incoming
    return existing


def _valid_thought_signature(signature: str | None) -> bool:
    if not signature:
        return False
    if len(signature) % 4 != 0:
        return False
    return bool(_BASE64_PATTERN.match(signature))


def _resolve_thought_signature(is_same_model: bool, signature: str | None) -> str | None:
    return signature if is_same_model and _valid_thought_signature(signature) else None


def requires_tool_call_id(model_id: str) -> bool:
    """Some Google-API-fronted models require explicit tool-call IDs."""
    return model_id.startswith("gpt-oss-")


def _gemini_major_version(model_id: str) -> int | None:
    match = re.match(r"^gemini(?:-live)?-(\d+)", model_id.lower())
    if not match:
        return None
    return int(match.group(1))


def _supports_multimodal_function_response(model_id: str) -> bool:
    version = _gemini_major_version(model_id)
    if version is None:
        return True
    return version >= 3


def convert_messages(model: Model[Any], context: Context) -> list[dict[str, Any]]:
    """Convert universal messages to Gemini ``Content[]`` format."""

    def _normalize_id(id_: str, _m: Model[Any], _src: AssistantMessage) -> str:
        if not requires_tool_call_id(model.id):
            return id_
        cleaned = "".join(ch if ch.isalnum() or ch in "_-" else "_" for ch in id_)
        return cleaned[:64]

    transformed = transform_messages(context.messages, model, _normalize_id)
    contents: list[dict[str, Any]] = []

    for msg in transformed:
        if isinstance(msg, UserMessage):
            if isinstance(msg.content, str):
                contents.append(
                    {"role": "user", "parts": [{"text": sanitize_surrogates(msg.content)}]}
                )
                continue
            parts: list[dict[str, Any]] = []
            for item in msg.content:
                if isinstance(item, TextContent):
                    parts.append({"text": sanitize_surrogates(item.text)})
                elif isinstance(item, (ImageContent, AudioContent)):
                    parts.append(
                        {"inline_data": {"mime_type": item.mime_type, "data": item.data}}
                    )
            if parts:
                contents.append({"role": "user", "parts": parts})
            continue

        if isinstance(msg, AssistantMessage):
            is_same_model = msg.provider == model.provider and msg.model == model.id
            parts = []

            for block in msg.content:
                if isinstance(block, TextContent):
                    if not block.text or not block.text.strip():
                        continue
                    sig = _resolve_thought_signature(is_same_model, block.text_signature)
                    part: dict[str, Any] = {"text": sanitize_surrogates(block.text)}
                    if sig:
                        part["thought_signature"] = sig
                    parts.append(part)
                elif isinstance(block, ThinkingContent):
                    if not block.thinking or not block.thinking.strip():
                        continue
                    if is_same_model:
                        sig = _resolve_thought_signature(is_same_model, block.thinking_signature)
                        part = {"thought": True, "text": sanitize_surrogates(block.thinking)}
                        if sig:
                            part["thought_signature"] = sig
                        parts.append(part)
                    else:
                        parts.append({"text": sanitize_surrogates(block.thinking)})
                elif isinstance(block, ToolCall):
                    sig = _resolve_thought_signature(is_same_model, block.thought_signature)
                    function_call: dict[str, Any] = {
                        "name": block.name,
                        "args": block.arguments or {},
                    }
                    if requires_tool_call_id(model.id):
                        function_call["id"] = block.id
                    part = {"function_call": function_call}
                    if sig:
                        part["thought_signature"] = sig
                    parts.append(part)

            if parts:
                contents.append({"role": "model", "parts": parts})
            continue

        if isinstance(msg, ToolResultMessage):
            text_blocks = [c for c in msg.content if isinstance(c, TextContent)]
            text_result = "\n".join(c.text for c in text_blocks)
            image_blocks = (
                [c for c in msg.content if isinstance(c, ImageContent)]
                if "image" in model.input
                else []
            )

            has_text = bool(text_result)
            has_images = bool(image_blocks)
            multimodal_fn_response = _supports_multimodal_function_response(model.id)

            response_value = (
                sanitize_surrogates(text_result)
                if has_text
                else ("(see attached image)" if has_images else "")
            )

            image_parts = [
                {"inline_data": {"mime_type": img.mime_type, "data": img.data}}
                for img in image_blocks
            ]

            include_id = requires_tool_call_id(model.id)
            function_response_part: dict[str, Any] = {
                "function_response": {
                    "name": msg.tool_name,
                    "response": (
                        {"error": response_value} if msg.is_error else {"output": response_value}
                    ),
                }
            }
            if has_images and multimodal_fn_response:
                function_response_part["function_response"]["parts"] = image_parts
            if include_id:
                function_response_part["function_response"]["id"] = msg.tool_call_id

            # Cloud Code Assist groups all function responses in one user turn.
            last = contents[-1] if contents else None
            if (
                last
                and last.get("role") == "user"
                and any("function_response" in p for p in last.get("parts", []))
            ):
                last.setdefault("parts", []).append(function_response_part)
            else:
                contents.append({"role": "user", "parts": [function_response_part]})

            if has_images and not multimodal_fn_response:
                contents.append(
                    {
                        "role": "user",
                        "parts": [{"text": "Tool result image:"}, *image_parts],
                    }
                )
            continue

    return contents


_JSON_SCHEMA_META_DECLARATIONS = frozenset(
    {"$schema", "$id", "$anchor", "$dynamicAnchor", "$vocabulary", "$comment", "$defs", "definitions"}
)


def _sanitize_for_openapi(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return schema
    return {
        key: _sanitize_for_openapi(value)
        for key, value in schema.items()
        if key not in _JSON_SCHEMA_META_DECLARATIONS
    }


def convert_tools(tools: list[Tool], use_parameters: bool = False) -> list[dict[str, Any]] | None:
    """Convert tools to Gemini ``functionDeclarations`` format.

    Defaults to ``parametersJsonSchema`` (full JSON Schema). Set
    ``use_parameters=True`` translates the legacy ``parameters`` field into
    ``input_schema`` for APIs that require it.
    """

    if not tools:
        return None

    declarations: list[dict[str, Any]] = []
    for tool in tools:
        declaration: dict[str, Any] = {"name": tool.name, "description": tool.description}
        if use_parameters:
            declaration["parameters"] = _sanitize_for_openapi(tool.parameters)
        else:
            declaration["parameters_json_schema"] = tool.parameters
        declarations.append(declaration)
    return [{"function_declarations": declarations}]


_TOOL_CHOICE_MAP = {
    "auto": "AUTO",
    "none": "NONE",
    "any": "ANY",
}


def map_tool_choice(choice: str) -> str:
    return _TOOL_CHOICE_MAP.get(choice, "AUTO")


def map_stop_reason(reason: Any) -> StopReason:
    """Map Gemini ``FinishReason`` (enum/string) to the locked StopReason."""

    name = getattr(reason, "name", None) or str(reason)
    if name in ("STOP", "FinishReason.STOP"):
        return "stop"
    if name in ("MAX_TOKENS", "FinishReason.MAX_TOKENS"):
        return "length"
    return "error"


def map_stop_reason_string(reason: str) -> StopReason:
    if reason == "STOP":
        return "stop"
    if reason == "MAX_TOKENS":
        return "length"
    return "error"


__all__ = [
    "GoogleThinkingLevel",
    "convert_messages",
    "convert_tools",
    "is_thinking_part",
    "map_stop_reason",
    "map_stop_reason_string",
    "map_tool_choice",
    "requires_tool_call_id",
    "retain_thought_signature",
]
