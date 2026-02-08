"""Utility classes for provider adapters."""

import hashlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .types import ToolCallResult


class ToolCallIdNormalizer:
    """Normalize tool call IDs for cross-provider compatibility.

    Different LLM providers have incompatible tool call ID formats:
    - OpenAI Responses API: 450+ chars with pipes and special characters
    - Anthropic Claude: <64 chars, alphanumeric + underscore/hyphen only
    - Gemini: Uses function name as ID (no separate ID field)

    This normalizer ensures IDs are compatible with the target provider.
    """

    MAX_ANTHROPIC_LENGTH = 64
    ALLOWED_CHARS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-")

    @classmethod
    def is_valid_for_anthropic(cls, id_str: str) -> bool:
        """Check if an ID is valid for Anthropic's constraints."""
        if len(id_str) > cls.MAX_ANTHROPIC_LENGTH:
            return False
        return all(c in cls.ALLOWED_CHARS for c in id_str)

    @classmethod
    def normalize(
        cls,
        original_id: str,
        target_provider: str = "anthropic",
    ) -> tuple[str, str | None]:
        """Normalize tool call ID for target provider constraints.

        Args:
            original_id: The original tool call ID
            target_provider: Target provider ("anthropic", "gemini", "openai")

        Returns:
            Tuple of (normalized_id, original_id_if_changed).
            If ID was already valid, returns (original_id, None).
        """
        if target_provider == "gemini":
            return (original_id, None)

        if target_provider in ("anthropic", "claude"):
            if cls.is_valid_for_anthropic(original_id):
                return (original_id, None)

            normalized = f"tc_{hashlib.sha256(original_id.encode()).hexdigest()[:29]}"
            return (normalized, original_id)

        return (original_id, None)

    @classmethod
    def normalize_tool_call(
        cls,
        tool_call: "ToolCallResult",
        target_provider: str = "anthropic",
    ) -> "ToolCallResult":
        """Normalize a ToolCallResult's ID for target provider.

        Args:
            tool_call: The tool call to normalize
            target_provider: Target provider

        Returns:
            New ToolCallResult with normalized ID (or same if unchanged)
        """
        from .types import ToolCallResult

        normalized_id, original = cls.normalize(tool_call.id, target_provider)
        if original is None:
            return tool_call

        return ToolCallResult(
            id=normalized_id,
            name=tool_call.name,
            input=tool_call.input,
            caller_type=tool_call.caller_type,
            caller_tool_id=tool_call.caller_tool_id,
            original_id=original,
        )
