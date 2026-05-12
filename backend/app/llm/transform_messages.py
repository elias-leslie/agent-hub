"""Universal message normalizer.

Direct port of pi-mono ``packages/ai/src/providers/transform-messages.ts``.
Producers run messages through :func:`transform_messages` before sending to
a provider. Behaviors:

* Image downgrade for non-vision models (per-content-block, with adjacency
  dedup so two images become one placeholder).
* Cross-model thinking blocks: redacted thinking is dropped, signed
  same-model thinking is preserved, others convert to plain text.
* Cross-model tool calls drop ``thought_signature``.
* Tool-call IDs may be normalized via a caller-supplied callback (for
  providers with shorter ID grammars). The mapping persists across the
  two-pass walk so subsequent tool-result messages match.
* Errored/aborted assistant turns are dropped to avoid replaying partial
  state (e.g. "reasoning without following item" on OpenAI).
* Synthetic ``"No result provided"`` (``is_error=True``) tool results are
  inserted for orphaned tool calls.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any

from .types import (
    AssistantMessage,
    ImageContent,
    Message,
    Model,
    TextContent,
    ThinkingContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

NON_VISION_USER_IMAGE_PLACEHOLDER = "(image omitted: model does not support images)"
NON_VISION_TOOL_IMAGE_PLACEHOLDER = "(tool image omitted: model does not support images)"


def _replace_images_with_placeholder(
    content: list[Any],
    placeholder: str,
) -> list[TextContent]:
    result: list[TextContent] = []
    previous_was_placeholder = False
    for block in content:
        if isinstance(block, ImageContent):
            if not previous_was_placeholder:
                result.append(TextContent(text=placeholder))
            previous_was_placeholder = True
            continue
        # Assume TextContent — pi-mono only allows TextContent | ImageContent here.
        if isinstance(block, TextContent):
            result.append(block)
            previous_was_placeholder = block.text == placeholder
        else:
            # Foreign block type — keep as-is for safety; placeholder run breaks.
            result.append(block)
            previous_was_placeholder = False
    return result


def _downgrade_unsupported_images(
    messages: list[Message],
    model: Model[Any],
) -> list[Message]:
    if "image" in model.input:
        return messages

    out: list[Message] = []
    for msg in messages:
        if isinstance(msg, UserMessage) and isinstance(msg.content, list):
            out.append(replace(msg, content=_replace_images_with_placeholder(msg.content, NON_VISION_USER_IMAGE_PLACEHOLDER)))
            continue
        if isinstance(msg, ToolResultMessage):
            out.append(replace(msg, content=_replace_images_with_placeholder(msg.content, NON_VISION_TOOL_IMAGE_PLACEHOLDER)))
            continue
        out.append(msg)
    return out


def transform_messages(
    messages: list[Message],
    model: Model[Any],
    normalize_tool_call_id: Callable[[str, Model[Any], AssistantMessage], str] | None = None,
) -> list[Message]:
    """Normalize messages for ``model``.

    See module docstring for the contract.
    """

    # Build a map of original tool-call IDs to normalized IDs.
    tool_call_id_map: dict[str, str] = {}
    image_aware_messages = _downgrade_unsupported_images(messages, model)

    # First pass: transform messages (image downgrade is already done above;
    # this pass handles thinking blocks + tool-call ID normalization).
    transformed: list[Message] = []
    for msg in image_aware_messages:
        if isinstance(msg, UserMessage):
            transformed.append(msg)
            continue

        if isinstance(msg, ToolResultMessage):
            normalized_id = tool_call_id_map.get(msg.tool_call_id)
            if normalized_id and normalized_id != msg.tool_call_id:
                transformed.append(replace(msg, tool_call_id=normalized_id))
            else:
                transformed.append(msg)
            continue

        if isinstance(msg, AssistantMessage):
            is_same_model = (
                msg.provider == model.provider
                and msg.api == model.api
                and msg.model == model.id
            )

            new_content: list[Any] = []
            for block in msg.content:
                if isinstance(block, ThinkingContent):
                    if block.redacted:
                        if is_same_model:
                            new_content.append(block)
                        continue
                    if is_same_model and block.thinking_signature:
                        new_content.append(block)
                        continue
                    if not block.thinking or block.thinking.strip() == "":
                        continue
                    if is_same_model:
                        new_content.append(block)
                        continue
                    new_content.append(TextContent(text=block.thinking))
                    continue

                if isinstance(block, TextContent):
                    if is_same_model:
                        new_content.append(block)
                    else:
                        new_content.append(TextContent(text=block.text))
                    continue

                if isinstance(block, ToolCall):
                    normalized_tool_call = block

                    if not is_same_model and block.thought_signature:
                        normalized_tool_call = replace(normalized_tool_call, thought_signature=None)

                    if not is_same_model and normalize_tool_call_id is not None:
                        normalized_id = normalize_tool_call_id(block.id, model, msg)
                        if normalized_id != block.id:
                            tool_call_id_map[block.id] = normalized_id
                            normalized_tool_call = replace(normalized_tool_call, id=normalized_id)

                    new_content.append(normalized_tool_call)
                    continue

                # Foreign block type — keep as-is.
                new_content.append(block)

            transformed.append(replace(msg, content=new_content))
            continue

        # Unknown role — pass through.
        transformed.append(msg)

    # Second pass: insert synthetic empty tool results for orphaned tool calls.
    # This preserves thinking signatures and satisfies API requirements.
    result: list[Message] = []
    pending_tool_calls: list[ToolCall] = []
    existing_tool_result_ids: set[str] = set()

    def insert_synthetic_tool_results() -> None:
        nonlocal pending_tool_calls, existing_tool_result_ids
        if not pending_tool_calls:
            return
        for tc in pending_tool_calls:
            if tc.id in existing_tool_result_ids:
                continue
            result.append(
                ToolResultMessage(
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    content=[TextContent(text="No result provided")],
                    is_error=True,
                    timestamp=int(time.time() * 1000),
                )
            )
        pending_tool_calls = []
        existing_tool_result_ids = set()

    for msg in transformed:
        if isinstance(msg, AssistantMessage):
            insert_synthetic_tool_results()

            # Skip errored/aborted assistant messages entirely. These are
            # incomplete turns that shouldn't be replayed:
            #   * may carry partial content (reasoning without message body,
            #     incomplete tool calls);
            #   * replaying causes API errors (OpenAI "reasoning without
            #     following item");
            #   * the model should retry from the last valid state.
            if msg.stop_reason in ("error", "aborted"):
                continue

            tool_calls = [b for b in msg.content if isinstance(b, ToolCall)]
            if tool_calls:
                pending_tool_calls = tool_calls
                existing_tool_result_ids = set()

            result.append(msg)
            continue

        if isinstance(msg, ToolResultMessage):
            existing_tool_result_ids.add(msg.tool_call_id)
            result.append(msg)
            continue

        if isinstance(msg, UserMessage):
            insert_synthetic_tool_results()
            result.append(msg)
            continue

        result.append(msg)

    # If the conversation ends with unresolved tool calls, synthesize results.
    insert_synthetic_tool_results()

    return result


__all__ = ["transform_messages"]
