"""Unit tests for ToolCallIdNormalizer."""

from app.adapters.base import ToolCallIdNormalizer, ToolCallResult


class TestToolCallIdNormalizer:
    """Tests for tool call ID normalization."""

    def test_short_valid_id_passes_through(self) -> None:
        """Short valid IDs should pass through unchanged."""
        valid_id = "call_abc123"
        normalized, original = ToolCallIdNormalizer.normalize(valid_id, "anthropic")
        assert normalized == valid_id
        assert original is None  # No change, so original not stored

    def test_valid_alphanumeric_with_underscore_hyphen(self) -> None:
        """IDs with alphanumeric, underscore, and hyphen should pass through."""
        valid_id = "tool-call_ABC-123_xyz"
        normalized, original = ToolCallIdNormalizer.normalize(valid_id, "anthropic")
        assert normalized == valid_id
        assert original is None

    def test_long_id_gets_hashed(self) -> None:
        """Long IDs (>64 chars) should be hashed."""
        long_id = "a" * 100
        normalized, original = ToolCallIdNormalizer.normalize(long_id, "anthropic")
        assert len(normalized) <= 64
        assert normalized.startswith("tc_")
        assert original == long_id

    def test_openai_style_id_gets_hashed(self) -> None:
        """OpenAI-style IDs with pipes and special chars should be hashed."""
        openai_id = "call_abc123|response_xyz|tool_def456|very|long|path|with|pipes"
        normalized, original = ToolCallIdNormalizer.normalize(openai_id, "anthropic")
        assert len(normalized) <= 64
        assert normalized.startswith("tc_")
        assert original == openai_id
        assert "|" not in normalized

    def test_id_with_special_chars_gets_hashed(self) -> None:
        """IDs with special characters (not alphanumeric/_/-) should be hashed."""
        special_id = "call@abc#123"
        normalized, original = ToolCallIdNormalizer.normalize(special_id, "anthropic")
        assert normalized.startswith("tc_")
        assert original == special_id

    def test_gemini_provider_passes_through(self) -> None:
        """Gemini provider should pass through all IDs unchanged."""
        long_id = "a" * 100
        normalized, original = ToolCallIdNormalizer.normalize(long_id, "gemini")
        assert normalized == long_id
        assert original is None

    def test_deterministic_hashing(self) -> None:
        """Same input should always produce same normalized ID."""
        long_id = "very_long_id_that_exceeds_sixty_four_characters_and_needs_hashing_" * 3
        normalized1, _ = ToolCallIdNormalizer.normalize(long_id, "anthropic")
        normalized2, _ = ToolCallIdNormalizer.normalize(long_id, "anthropic")
        assert normalized1 == normalized2

    def test_different_ids_produce_different_hashes(self) -> None:
        """Different input IDs should produce different normalized IDs."""
        id1 = "a" * 100
        id2 = "b" * 100
        normalized1, _ = ToolCallIdNormalizer.normalize(id1, "anthropic")
        normalized2, _ = ToolCallIdNormalizer.normalize(id2, "anthropic")
        assert normalized1 != normalized2

    def test_is_valid_for_anthropic_short_valid(self) -> None:
        """Valid short IDs should pass validation."""
        assert ToolCallIdNormalizer.is_valid_for_anthropic("call_123")
        assert ToolCallIdNormalizer.is_valid_for_anthropic("abc-def_123")

    def test_is_valid_for_anthropic_too_long(self) -> None:
        """IDs over 64 chars should fail validation."""
        assert not ToolCallIdNormalizer.is_valid_for_anthropic("a" * 65)

    def test_is_valid_for_anthropic_special_chars(self) -> None:
        """IDs with special chars should fail validation."""
        assert not ToolCallIdNormalizer.is_valid_for_anthropic("call|123")
        assert not ToolCallIdNormalizer.is_valid_for_anthropic("call@123")
        assert not ToolCallIdNormalizer.is_valid_for_anthropic("call 123")

    def test_empty_id(self) -> None:
        """Empty ID should pass through (edge case)."""
        normalized, original = ToolCallIdNormalizer.normalize("", "anthropic")
        assert normalized == ""
        assert original is None

    def test_exactly_64_chars_valid(self) -> None:
        """ID with exactly 64 valid chars should pass through."""
        valid_64 = "a" * 64
        normalized, original = ToolCallIdNormalizer.normalize(valid_64, "anthropic")
        assert normalized == valid_64
        assert original is None

    def test_exactly_65_chars_gets_hashed(self) -> None:
        """ID with 65 chars should be hashed."""
        long_65 = "a" * 65
        normalized, original = ToolCallIdNormalizer.normalize(long_65, "anthropic")
        assert len(normalized) <= 64
        assert normalized.startswith("tc_")
        assert original == long_65


class TestToolCallIdNormalizerToolCall:
    """Tests for normalize_tool_call method."""

    def test_normalize_tool_call_valid_id(self) -> None:
        """Valid tool call should be returned unchanged."""
        tool_call = ToolCallResult(
            id="call_123",
            name="search",
            input={"query": "test"},
        )
        normalized = ToolCallIdNormalizer.normalize_tool_call(tool_call, "anthropic")
        assert normalized is tool_call  # Same object returned
        assert normalized.original_id is None

    def test_normalize_tool_call_long_id(self) -> None:
        """Tool call with long ID should have normalized ID and original preserved."""
        original_id = "a" * 100
        tool_call = ToolCallResult(
            id=original_id,
            name="search",
            input={"query": "test"},
        )
        normalized = ToolCallIdNormalizer.normalize_tool_call(tool_call, "anthropic")
        assert normalized is not tool_call  # New object created
        assert len(normalized.id) <= 64
        assert normalized.original_id == original_id
        assert normalized.name == "search"
        assert normalized.input == {"query": "test"}

    def test_normalize_tool_call_preserves_caller_fields(self) -> None:
        """Normalized tool call should preserve caller_type and caller_tool_id."""
        tool_call = ToolCallResult(
            id="a" * 100,
            name="write_file",
            input={"path": "/test"},
            caller_type="code_execution_20250825",
            caller_tool_id="parent_123",
        )
        normalized = ToolCallIdNormalizer.normalize_tool_call(tool_call, "anthropic")
        assert normalized.caller_type == "code_execution_20250825"
        assert normalized.caller_tool_id == "parent_123"

    def test_normalize_tool_call_gemini_passthrough(self) -> None:
        """Gemini target should return tool call unchanged."""
        tool_call = ToolCallResult(
            id="a" * 100,
            name="search",
            input={},
        )
        normalized = ToolCallIdNormalizer.normalize_tool_call(tool_call, "gemini")
        assert normalized is tool_call
