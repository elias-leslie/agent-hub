"""Tests for variant assignment (ac-002 verification)."""

from app.services.memory.variants import MemoryVariant, assign_variant


class TestVariantAssignmentDeterminism:
    """Tests to verify deterministic variant assignment (ac-002)."""

    def test_same_task_id_same_variant(self):
        """Test same task_id always gets same variant."""
        task_id = "task-abc123"
        project_id = "summitflow"

        v1 = assign_variant(external_id=task_id, project_id=project_id)
        v2 = assign_variant(external_id=task_id, project_id=project_id)
        v3 = assign_variant(external_id=task_id, project_id=project_id)

        assert v1 == v2 == v3, "Same inputs must produce same variant"

    def test_determinism_across_runs(self):
        """Test variant assignment is deterministic across multiple calls."""
        # Simulate multiple sessions/calls with same identifiers
        results = []
        for _ in range(100):
            v = assign_variant(external_id="task-xyz789", project_id="agent-hub")
            results.append(v)

        # All results should be identical
        assert len(set(results)) == 1, "All calls with same input must return same variant"

    def test_different_tasks_can_get_different_variants(self):
        """Test different task IDs can get different variants."""
        variants_seen = set()

        # Try many different task IDs
        for i in range(500):
            v = assign_variant(external_id=f"task-{i}", project_id="test-project")
            variants_seen.add(v)

        # Should see multiple different variants
        assert len(variants_seen) >= 2, "Different inputs should produce variety"

    def test_variant_override_always_works(self):
        """Test variant override parameter always takes precedence."""
        for expected in MemoryVariant:
            v = assign_variant(
                external_id="task-123",
                project_id="any-project",
                variant_override=expected,
            )
            assert v == expected, f"Override {expected} must be respected"

    def test_reproducibility_for_same_input(self):
        """Test exact same inputs always produce exact same output."""
        # Known inputs
        test_cases = [
            ("task-001", "proj-a"),
            ("task-002", "proj-b"),
            ("external-id-xyz", "my-project"),
            ("session-abc", None),
            (None, "only-project"),
        ]

        for external_id, project_id in test_cases:
            # Get variant twice
            v1 = assign_variant(external_id=external_id, project_id=project_id)
            v2 = assign_variant(external_id=external_id, project_id=project_id)

            assert v1 == v2, f"Same inputs ({external_id}, {project_id}) must be deterministic"
