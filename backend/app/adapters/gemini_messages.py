"""Message and content conversion for Gemini adapter."""

import base64
from typing import Any

from google.genai import types

from app.adapters.base import Message


def build_parts(content: str | list[dict[str, Any]]) -> list[types.Part]:
    """Build Gemini parts from content.

    Args:
        content: Either a string or list of content blocks (text/image).

    Returns:
        List of Gemini Part objects.
    """
    if isinstance(content, str):
        return [types.Part(text=content)]

    parts: list[types.Part] = []
    for block in content:
        if isinstance(block, str):
            parts.append(types.Part(text=block))
        elif isinstance(block, dict):
            block_type = block.get("type")
            if block_type == "text":
                parts.append(types.Part(text=block.get("text", "")))
            elif block_type == "image":
                parts.append(_build_image_part(block))
    return parts


def _build_image_part(block: dict[str, Any]) -> types.Part:
    """Build Gemini Part from image block.

    Args:
        block: Image block with source containing type, media_type, and data.

    Returns:
        Gemini Part with inline image data.
    """
    source = block.get("source", {})
    if source.get("type") == "base64":
        media_type = source.get("media_type", "image/png")
        data = source.get("data", "")
        image_bytes = base64.b64decode(data)
        return types.Part.from_bytes(data=image_bytes, mime_type=media_type)
    return types.Part(text="")


def convert_messages(
    messages: list[Message],
) -> tuple[str | None, list[types.Content]]:
    """Convert messages to Gemini format.

    Args:
        messages: List of Message objects

    Returns:
        Tuple of (system_instruction, contents)
    """
    system_instruction: str | None = None
    contents: list[types.Content] = []

    for msg in messages:
        if msg.role == "system":
            system_instruction = _extract_system_content(msg)
        else:
            contents.append(_convert_message(msg))

    return system_instruction, contents


def _extract_system_content(msg: Message) -> str:
    """Extract system message content as string.

    Args:
        msg: System message

    Returns:
        System instruction as string
    """
    return msg.content if isinstance(msg.content, str) else str(msg.content)


def _convert_message(msg: Message) -> types.Content:
    """Convert single message to Gemini Content.

    Args:
        msg: Message to convert

    Returns:
        Gemini Content object
    """
    role = "model" if msg.role == "assistant" else "user"
    parts = build_parts(msg.content)
    return types.Content(role=role, parts=parts)
