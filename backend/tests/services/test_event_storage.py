"""Tests for event storage: sequencer turn/sequence tracking and content extraction."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.services.event_storage import (
    EventSequencer,
    _extract_tool_result_content,
    store_memory_inject_event,
)


class TestEventSequencer:
    """Tests for EventSequencer turn/sequence state machine."""

    def test_auto_initializes_on_first_access(self) -> None:
        seq = EventSequencer()
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 1
        assert sequence == 1

    def test_sequence_increments_within_turn(self) -> None:
        seq = EventSequencer()
        seq.get_turn_sequence("sess-1")
        _, s2 = seq.get_turn_sequence("sess-1")
        _, s3 = seq.get_turn_sequence("sess-1")
        assert s2 == 2
        assert s3 == 3

    def test_next_turn_advances_and_resets_sequence(self) -> None:
        seq = EventSequencer()
        seq.get_turn_sequence("sess-1")
        seq.get_turn_sequence("sess-1")
        new_turn = seq.next_turn("sess-1")
        assert new_turn == 2
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 2
        assert sequence == 1

    def test_set_turn_initializes_new_session(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 5)
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 5
        assert sequence == 1

    def test_set_turn_with_min_sequence(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 3, min_sequence=7)
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 3
        assert sequence == 8

    def test_set_turn_never_goes_backward(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 5, min_sequence=10)
        seq.set_turn("sess-1", 3)
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 5
        assert sequence == 11

    def test_set_turn_same_turn_advances_sequence(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 3, min_sequence=2)
        seq.set_turn("sess-1", 3, min_sequence=8)
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 3
        assert sequence == 9

    def test_set_turn_same_turn_does_not_regress_sequence(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 3, min_sequence=10)
        seq.set_turn("sess-1", 3, min_sequence=5)
        turn, sequence = seq.get_turn_sequence("sess-1")
        assert turn == 3
        assert sequence == 11

    def test_session_isolation(self) -> None:
        seq = EventSequencer()
        seq.set_turn("sess-1", 5)
        seq.set_turn("sess-2", 1)
        t1, s1 = seq.get_turn_sequence("sess-1")
        t2, s2 = seq.get_turn_sequence("sess-2")
        assert t1 == 5
        assert s1 == 1
        assert t2 == 1
        assert s2 == 1

    def test_resume_session_scenario(self) -> None:
        """Simulate the session continuation flow:
        1. First request stores events at turn 1
        2. Second request resumes with set_turn(2)
        3. Endpoint stores memory_inject
        4. complete_internal calls set_turn(2) again with higher sequence
        """
        seq = EventSequencer()
        seq.get_turn_sequence("sess-1")
        seq.get_turn_sequence("sess-1")
        seq.get_turn_sequence("sess-1")

        seq.set_turn("sess-1", 2)
        _, s = seq.get_turn_sequence("sess-1")
        assert s == 1

        seq.set_turn("sess-1", 2, min_sequence=1)
        _, s = seq.get_turn_sequence("sess-1")
        assert s == 2

    def test_forward_only_prevents_collision(self) -> None:
        """The critical bug scenario: sequencer already at turn=2, seq=5
        and a stale get_or_create_session tries set_turn(2, 0).
        Should NOT reset sequence to 0."""
        seq = EventSequencer()
        seq.set_turn("sess-1", 2, min_sequence=0)
        seq.get_turn_sequence("sess-1")
        seq.get_turn_sequence("sess-1")
        seq.get_turn_sequence("sess-1")

        seq.set_turn("sess-1", 2, min_sequence=0)
        _, s = seq.get_turn_sequence("sess-1")
        assert s == 4


class TestExtractToolResultContent:
    """Tests for _extract_tool_result_content helper."""

    # -- Common keys in priority order -----------------------------------

    def test_extract_result_key_returns_value(self) -> None:
        assert _extract_tool_result_content({"result": "hello"}) == "hello"

    def test_extract_content_key_returns_value(self) -> None:
        assert _extract_tool_result_content({"content": "world"}) == "world"

    def test_extract_output_key_returns_value(self) -> None:
        assert _extract_tool_result_content({"output": "data here"}) == "data here"

    def test_extract_message_key_returns_value(self) -> None:
        assert _extract_tool_result_content({"message": "ok"}) == "ok"

    # -- Priority order: first matching key wins -------------------------

    def test_extract_multiple_keys_first_priority_wins(self) -> None:
        """When multiple known keys exist, 'result' wins over 'content'."""
        data = {"content": "second", "result": "first", "message": "third"}
        assert _extract_tool_result_content(data) == "first"


class TestMemoryInjectEvent:
    @pytest.mark.asyncio
    async def test_store_memory_inject_event_includes_reference_breakdown(self) -> None:
        db = MagicMock()

        event = await store_memory_inject_event(
            db=db,
            session_id="sess-1",
            memory_uuids=["m1", "m2", "r1"],
            memory_count=3,
            reference_selected_uuids=["r1"],
            reference_index_uuids=["r2", "r3"],
            agent_id="persona",
        )

        assert "refs selected=1 index=2" in event.content
        assert event.tool_input["reference_selected_count"] == 1
        assert event.tool_input["reference_index_count"] == 2
        assert event.tool_input["reference_selected_uuids"] == ["r1"]
        assert event.tool_input["reference_index_uuids"] == ["r2", "r3"]

    def test_extract_content_beats_output(self) -> None:
        """'content' has higher priority than 'output'."""
        data = {"output": "low", "content": "high"}
        assert _extract_tool_result_content(data) == "high"

    def test_extract_output_beats_message(self) -> None:
        """'output' has higher priority than 'message'."""
        data = {"message": "low", "output": "high"}
        assert _extract_tool_result_content(data) == "high"

    # -- Single-key fallback ---------------------------------------------

    def test_extract_single_unknown_key_string_returns_value(self) -> None:
        """A single-key dict with a string value falls back to that value."""
        assert _extract_tool_result_content({"summary": "all good"}) == "all good"

    def test_extract_single_unknown_key_non_string_returns_none(self) -> None:
        """A single-key dict with a non-string value returns None."""
        assert _extract_tool_result_content({"count": 42}) is None

    # -- Nested / multi-key dicts without known keys ---------------------

    def test_extract_nested_content_not_found_returns_none(self) -> None:
        """Nested dicts under unknown keys are not traversed."""
        data = {"status": "ok", "data": {"content": "buried"}}
        assert _extract_tool_result_content(data) is None

    def test_extract_multi_unknown_keys_returns_none(self) -> None:
        """Multiple unknown keys with no known key returns None."""
        data = {"status": "ok", "code": "200"}
        assert _extract_tool_result_content(data) is None

    # -- Empty dict ------------------------------------------------------

    def test_extract_empty_dict_returns_none(self) -> None:
        assert _extract_tool_result_content({}) is None

    # -- Non-string values for known keys --------------------------------

    def test_extract_known_key_int_value_returns_none(self) -> None:
        """Known key 'result' with int value is skipped."""
        assert _extract_tool_result_content({"result": 42}) is None

    def test_extract_known_key_list_value_returns_none(self) -> None:
        """Known key 'content' with list value is skipped."""
        assert _extract_tool_result_content({"content": ["a", "b"]}) is None

    def test_extract_known_key_dict_value_returns_none(self) -> None:
        """Known key 'output' with dict value is skipped."""
        assert _extract_tool_result_content({"output": {"nested": "value"}}) is None

    def test_extract_known_key_empty_string_skips_priority_uses_fallback(self) -> None:
        """Known key with empty string is falsy so priority loop skips it,
        but the single-key fallback still returns the empty string."""
        assert _extract_tool_result_content({"result": ""}) == ""

    def test_extract_known_key_empty_string_with_other_keys_returns_none(self) -> None:
        """Empty string in known key with multiple keys (no single-key fallback) returns None."""
        assert _extract_tool_result_content({"result": "", "extra": 123}) is None

    # -- Truncation at 2000 chars ----------------------------------------

    def test_extract_truncates_at_2000_chars(self) -> None:
        long_text = "x" * 3000
        result = _extract_tool_result_content({"result": long_text})
        assert result is not None
        assert len(result) == 2000
        assert result == "x" * 2000

    def test_extract_no_truncation_under_2000_chars(self) -> None:
        text = "y" * 1999
        result = _extract_tool_result_content({"result": text})
        assert result == text

    def test_extract_single_key_fallback_also_truncates(self) -> None:
        """Single-key fallback path also respects the 2000-char cap."""
        long_text = "z" * 2500
        result = _extract_tool_result_content({"custom_field": long_text})
        assert result is not None
        assert len(result) == 2000
