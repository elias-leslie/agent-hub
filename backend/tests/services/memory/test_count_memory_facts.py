from types import SimpleNamespace

from app.services.memory.context_builder import count_memory_facts


def test_count_memory_facts_sums_all_blocks_and_tolerates_partial_doubles() -> None:
    full = SimpleNamespace(mandates=[1], guardrails=[1, 2], reference_index=[1], reference=[1, 2, 3])
    assert count_memory_facts(full) == 7
    assert count_memory_facts(SimpleNamespace(mandates=[1, 2])) == 2
