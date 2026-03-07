"""Tests for shared memory utility score normalization."""

from app.models.memory_unified import Memory
from app.services.memory_utility_score import calculate_memory_utility_score


def test_calculate_memory_utility_score_caps_over_cited_memories() -> None:
    assert calculate_memory_utility_score(loaded_count=2, referenced_count=25) == 1.0


def test_calculate_memory_utility_score_uses_loaded_ratio() -> None:
    assert calculate_memory_utility_score(loaded_count=4, referenced_count=2) == 0.5


def test_memory_model_utility_score_uses_normalized_contract() -> None:
    memory = Memory(
        content="test",
        memory_type="reference",
        scope="global",
        loaded_count=2,
        referenced_count=25,
    )

    assert memory.utility_score == 1.0
