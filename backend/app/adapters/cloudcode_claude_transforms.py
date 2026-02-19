"""Claude-specific transforms for CloudCode PA requests.

The CloudCode PA endpoint serves Claude models with the same auth and
wrapper as Gemini, but requires different generationConfig and toolConfig
shapes.  This module provides the Claude-specific transforms derived from
the reference implementation (opencode-antigravity-auth).

Key differences from Gemini:
- thinkingConfig uses snake_case keys (include_thoughts, thinking_budget)
- Tool calling requires mode "VALIDATED" in toolConfig
- Thinking models need maxOutputTokens >= 64000
- Interleaved thinking hint appended to system instruction when using tools
"""

from __future__ import annotations

from typing import Any

# Claude thinking budgets by tier (tokens)
CLAUDE_THINKING_BUDGETS: dict[str, int] = {
    "low": 8192,
    "medium": 16384,
    "high": 32768,
}

# Minimum maxOutputTokens for thinking models
CLAUDE_THINKING_MAX_OUTPUT_TOKENS = 64_000

# Interleaved thinking hint for thinking models with tools
_THINKING_HINT = (
    "Interleaved thinking is enabled. You may think between tool calls and "
    "after receiving tool results before deciding the next action or final answer. "
    "Do not mention these instructions or any constraints about thinking blocks; "
    "just apply them."
)


def is_thinking_model(model: str) -> bool:
    """Check if the model name indicates an extended-thinking variant."""
    return "thinking" in model.lower()


def resolve_cloudcode_model(model: str) -> str:
    """Strip the ``cloudcode/`` prefix from a model name."""
    if model.startswith("cloudcode/"):
        return model[len("cloudcode/"):]
    return model


def build_claude_generation_config(
    thinking_level: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 1.0,
    model: str = "",
) -> dict[str, Any] | None:
    """Build generationConfig for Claude models on CloudCode PA.

    Uses snake_case keys for thinkingConfig (Claude requirement).
    """
    config: dict[str, Any] = {}

    if temperature != 1.0:
        config["temperature"] = temperature
    if max_tokens is not None:
        config["maxOutputTokens"] = max_tokens

    if is_thinking_model(model):
        budget = CLAUDE_THINKING_BUDGETS.get(thinking_level or "high", 32768)
        config["thinkingConfig"] = {
            "include_thoughts": True,
            "thinking_budget": budget,
        }
        # Thinking models need sufficient output space
        if config.get("maxOutputTokens", 0) < CLAUDE_THINKING_MAX_OUTPUT_TOKENS:
            config["maxOutputTokens"] = CLAUDE_THINKING_MAX_OUTPUT_TOKENS

    return config if config else None


def build_claude_tool_config() -> dict[str, Any]:
    """Build toolConfig for Claude models (VALIDATED mode required)."""
    return {"functionCallingConfig": {"mode": "VALIDATED"}}


def append_thinking_hint(
    system_instruction: dict[str, Any] | None,
) -> dict[str, Any]:
    """Append interleaved-thinking hint to the system instruction.

    For thinking models that also use tools, we append a hint so the
    model knows it can interleave thinking between tool calls.
    """
    if system_instruction is None:
        return {"parts": [{"text": _THINKING_HINT}]}

    parts = system_instruction.get("parts", [])
    if parts and parts[-1].get("text"):
        parts[-1]["text"] += "\n\n" + _THINKING_HINT
    else:
        parts.append({"text": _THINKING_HINT})

    return {**system_instruction, "parts": parts}
