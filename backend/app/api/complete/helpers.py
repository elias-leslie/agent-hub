"""Helper functions for completion API."""

from __future__ import annotations

import json
import logging
from typing import Any

import jsonschema

from app.adapters.base import Message
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.adapters.openai import OpenAIAdapter
from app.adapters.openrouter import OpenRouterAdapter
from app.constants import (
    CLAUDE_HAIKU,
    CLAUDE_OPUS,
    CLAUDE_SONNET,
    GEMINI_FLASH,
    GEMINI_PRO,
    OR_GEMINI_3_FLASH,
    OR_GEMINI_3_PRO,
    OR_GROK_4_1,
    OR_GROK_CODE,
    OR_KIMI_K2_5,
    OR_MINIMAX_2_1,
)

logger = logging.getLogger(__name__)


def validate_json_response(content: str, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate JSON response against a JSON Schema.

    Args:
        content: The response content (should be valid JSON).
        schema: The JSON Schema to validate against.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        # Parse the JSON content
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    try:
        # Validate against schema
        jsonschema.validate(instance=parsed, schema=schema)
        return True, None
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"


def get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if model_lower.startswith("openrouter/") or model_lower.startswith("or/"):
        return "openrouter"
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    elif "gpt" in model_lower or "openai" in model_lower:
        return "openai"
    else:
        # Default to claude for unknown models
        return "claude"


# Auto-thinking detection configuration
# Inspired by Claude Code UX: Tab toggle, "ultrathink" trigger, sticky state
# See: https://claudelog.com/faqs/how-to-toggle-thinking-in-claude-code/

# Keywords that suggest complex reasoning where thinking helps
_THINKING_TRIGGERS = [
    # Explicit thinking requests (Claude Code style)
    "ultrathink",  # Maximum budget trigger
    "think hard",
    "think carefully",
    "think step by step",
    # Analysis tasks
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    # Reasoning tasks
    "reason",
    "think through",
    "consider carefully",
    # Code tasks
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    # Complexity markers
    "multi-step",
    "complex",
    "edge cases",
]

MENTION_ALIASES: dict[str, str] = {
    "sonnet": CLAUDE_SONNET,
    "opus": CLAUDE_OPUS,
    "haiku": CLAUDE_HAIKU,
    "flash": GEMINI_FLASH,
    "pro": GEMINI_PRO,
    # OpenRouter aliases
    "or/grok": OR_GROK_CODE,
    "or/grok-fast": OR_GROK_4_1,
    "or/kimi": OR_KIMI_K2_5,
    "or/gemini-flash": OR_GEMINI_3_FLASH,
    "or/gemini-pro": OR_GEMINI_3_PRO,
    "or/minimax": OR_MINIMAX_2_1,
}


def extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text content from message content.

    Args:
        content: String or list of content blocks.

    Returns:
        Extracted text content.
    """
    if isinstance(content, str):
        return content
    # Extract text from content blocks
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def parse_mention(content: str | list[dict[str, Any]]) -> tuple[str | None, str]:
    """Extract @model mention from message content.

    Supports aliases: @sonnet, @opus, @haiku, @flash, @pro (case-insensitive).
    Also supports full model names like @claude-sonnet-4-5.

    Args:
        content: Message content (string or content blocks).

    Returns:
        Tuple of (resolved_model, cleaned_content) where resolved_model is None if no mention.
    """
    import re

    text = extract_text_content(content) if isinstance(content, list) else content
    pattern = r"@(\w+[-\w]*)"
    match = re.search(pattern, text, re.IGNORECASE)
    if not match:
        return None, text

    mention = match.group(1).lower()
    resolved_model = MENTION_ALIASES.get(mention)
    if not resolved_model:
        from app.constants import MODEL_ALIASES

        if mention in MODEL_ALIASES:
            resolved_model = MODEL_ALIASES[mention]
        elif (
            mention.startswith("claude")
            or mention.startswith("gemini")
            or mention.startswith("gpt")
        ):
            resolved_model = mention

    if not resolved_model:
        return None, text

    cleaned = re.sub(r"@\w+[-\w]*\s*", "", text, count=1).strip()
    return resolved_model, cleaned


def should_enable_thinking(messages: list[Message]) -> bool:
    """Detect if request would benefit from extended thinking.

    Triggers on:
    - Explicit thinking keywords (ultrathink, think hard, etc.)
    - Keywords suggesting complex reasoning
    - Multi-step instructions (numbered lists)
    - Code review/analysis requests
    """
    # Check the last user message
    for msg in reversed(messages):
        if msg.role == "user":
            text_content = extract_text_content(msg.content)
            content_lower = text_content.lower()
            for trigger in _THINKING_TRIGGERS:
                if trigger in content_lower:
                    return True
            # Also trigger on numbered steps (1. 2. 3.)
            if any(f"{i}." in text_content for i in range(1, 10)):
                return True
            break
    return False


# Cached adapter instances - created once, reused across requests
_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter | OpenAIAdapter | OpenRouterAdapter] = {}


def get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter | OpenAIAdapter | OpenRouterAdapter:
    """Get cached adapter instance for provider."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    if provider == "claude":
        adapter: ClaudeAdapter | GeminiAdapter | OpenAIAdapter | OpenRouterAdapter = ClaudeAdapter()
    elif provider == "gemini":
        adapter = GeminiAdapter()
    elif provider == "openai":
        adapter = OpenAIAdapter()
    elif provider == "openrouter":
        adapter = OpenRouterAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    _adapter_cache[provider] = adapter
    logger.info(f"Created cached adapter for {provider}")
    return adapter


def clear_adapter_cache() -> None:
    """Clear the adapter cache. Useful for testing."""
    _adapter_cache.clear()


def normalize_content_for_storage(content: str | list[Any]) -> str:
    """Normalize message content for database storage.

    Multi-modal content (list of text/image blocks) is serialized to JSON.
    """
    if isinstance(content, list):
        import json

        return json.dumps(content)
    return content


def is_error_response(content: str) -> bool:
    """Detect error responses that should not be cached."""
    error_indicators = [
        "Usage Policy",
        "violate",
        "unable to respond to this request",
        "rate limit",
        "authentication failed",
    ]
    content_lower = content.lower()
    return any(ind.lower() in content_lower for ind in error_indicators)
