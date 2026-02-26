"""Message, tool, and config conversion helpers for CloudCode PA.

Internal module — import public API from gemini_cloudcode.py.
"""

from __future__ import annotations

from typing import Any

from app.adapters.base import Message


def convert_messages_for_cloudcode(
    messages: list[Message],
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Convert Message objects to cloudcode-pa format.

    Returns:
        (system_instruction_dict | None, contents_list)
    """
    system_instruction: dict[str, Any] | None = None
    contents: list[dict[str, Any]] = []

    for msg in messages:
        if msg.role == "system":
            text = msg.content if isinstance(msg.content, str) else str(msg.content)
            system_instruction = {"parts": [{"text": text}]}
        else:
            role = "model" if msg.role == "assistant" else "user"
            parts = _build_content_parts(msg.content)
            contents.append({"role": role, "parts": parts})

    return system_instruction, contents


def _build_content_parts(
    content: str | list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert content to cloudcode parts format."""
    if isinstance(content, str):
        return [{"text": content}]

    parts: list[dict[str, Any]] = []
    for block in content:
        if isinstance(block, str):
            parts.append({"text": block})
        elif isinstance(block, dict):
            _append_block_part(parts, block)
    return parts


def _append_block_part(
    parts: list[dict[str, Any]],
    block: dict[str, Any],
) -> None:
    """Append a single content block to parts list."""
    block_type = block.get("type")
    if block_type == "text":
        parts.append({"text": block.get("text", "")})
    elif block_type == "image":
        source = block.get("source", {})
        if source.get("type") == "base64":
            parts.append({
                "inlineData": {
                    "mimeType": source.get("media_type", "image/png"),
                    "data": source.get("data", ""),
                },
            })
    elif block_type == "tool_use":
        fc_part: dict[str, Any] = {
            "functionCall": {
                "name": block.get("name", ""),
                "args": block.get("input", {}),
            },
        }
        if block.get("thought_signature"):
            fc_part["thoughtSignature"] = block["thought_signature"]
        parts.append(fc_part)
    elif block_type == "tool_result":
        parts.append({
            "functionResponse": {
                "name": block.get("tool_name", ""),
                "response": {"result": block.get("content", "")},
            },
        })


def build_cloudcode_tools(
    tools: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert tool definitions to cloudcode functionDeclarations format."""
    declarations = []
    for t in tools:
        decl: dict[str, Any] = {
            "name": t.get("name", ""),
            "description": t.get("description", ""),
        }
        schema = t.get("input_schema") or t.get("parameters")
        if schema:
            decl["parameters"] = _to_gemini_schema(schema)
        declarations.append(decl)
    return [{"functionDeclarations": declarations}]


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON Schema to Gemini-compatible format (uppercase types)."""
    result: dict[str, Any] = {}

    if "type" in schema:
        result["type"] = schema["type"].upper()
    if "description" in schema:
        result["description"] = schema["description"]
    if "enum" in schema:
        result["enum"] = schema["enum"]
    if "required" in schema:
        result["required"] = schema["required"]

    if "properties" in schema:
        result["properties"] = {
            k: _to_gemini_schema(v) for k, v in schema["properties"].items()
        }

    if "items" in schema:
        result["items"] = _to_gemini_schema(schema["items"])

    for key in ("anyOf", "oneOf", "allOf"):
        if key in schema:
            result[key] = [_to_gemini_schema(s) for s in schema[key]]

    return result


def build_generation_config(
    temperature: float = 1.0,
    max_tokens: int | None = None,
    model: str = "",
    thinking_level: str | None = None,
) -> dict[str, Any] | None:
    """Build generationConfig for cloudcode-pa requests."""
    config: dict[str, Any] = {}

    if temperature != 1.0:
        config["temperature"] = temperature
    if max_tokens is not None:
        config["maxOutputTokens"] = max_tokens

    if thinking_level and "gemini-3" in model:
        from app.adapters.gemini_thinking import (
            THINKING_LEVEL_MAP_FLASH,
            THINKING_LEVEL_MAP_PRO,
        )

        is_pro = "pro" in model.lower()
        level_map = THINKING_LEVEL_MAP_PRO if is_pro else THINKING_LEVEL_MAP_FLASH
        level = level_map.get(thinking_level, "high")
        config["thinkingConfig"] = {
            "includeThoughts": True,
            "thinkingLevel": level.upper(),
        }

    return config if config else None
