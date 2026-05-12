"""Tests for cost wiring in SSE done events."""

from __future__ import annotations

from app.api.complete.response_schemas import StreamingChunk


class TestStreamingChunkCostFields:
    """Verify StreamingChunk includes cost/cache fields."""

    def test_done_chunk_with_cost(self):
        """Done chunk should include cost_usd field."""
        chunk = StreamingChunk(
            type="done",
            model="claude-sonnet-4-6",
            provider="claude",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=0.0045,
        )
        data = chunk.model_dump()
        assert data["cost_usd"] == 0.0045
        assert data["input_tokens"] == 1000
        assert data["output_tokens"] == 500

    def test_done_chunk_with_thinking_tokens(self):
        """Done chunk should include thinking_tokens."""
        chunk = StreamingChunk(
            type="done",
            model="claude-opus-4-6",
            provider="claude",
            input_tokens=1000,
            output_tokens=500,
            thinking_tokens=2000,
            cost_usd=0.05,
        )
        data = chunk.model_dump()
        assert data["thinking_tokens"] == 2000

    def test_done_chunk_with_cache_tokens(self):
        """Done chunk should include cache_read/write tokens."""
        chunk = StreamingChunk(
            type="done",
            model="claude-sonnet-4-6",
            provider="claude",
            input_tokens=5000,
            output_tokens=1000,
            cache_read_tokens=4000,
            cache_write_tokens=1000,
            cost_usd=0.003,
        )
        data = chunk.model_dump()
        assert data["cache_read_tokens"] == 4000
        assert data["cache_write_tokens"] == 1000

    def test_cost_fields_default_to_none(self):
        """Cost fields should default to None for non-done events."""
        chunk = StreamingChunk(type="content", content="hello")
        data = chunk.model_dump()
        assert data["cost_usd"] is None
        assert data["thinking_tokens"] is None
        assert data["cache_read_tokens"] is None
        assert data["cache_write_tokens"] is None

    def test_json_excludes_none_values(self):
        """JSON serialization should include None fields (Pydantic default)."""
        chunk = StreamingChunk(type="content", content="hello")
        json_str = chunk.model_dump_json()
        # cost_usd should appear as null in JSON (Pydantic includes None by default)
        assert "cost_usd" in json_str


class TestMessageProvenance:
    """Verify message provenance fields."""

    def test_message_provenance(self):
        """Message should accept provider/model provenance fields."""
        from app.services.llm_messages import Message

        msg = Message(
            role="assistant",
            content="Hello",
            provider="claude",
            model="claude-sonnet-4-6",
        )
        assert msg.provider == "claude"
        assert msg.model == "claude-sonnet-4-6"

    def test_message_provenance_defaults_to_none(self):
        """Message provenance should default to None."""
        from app.services.llm_messages import Message

        msg = Message(role="user", content="Hi")
        assert msg.provider is None
        assert msg.model is None
