"""Tests for event sequencer turn/sequence tracking."""

from __future__ import annotations

from app.services.event_storage import EventSequencer


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
