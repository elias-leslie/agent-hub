"""Unit tests for SQLAlchemy models."""

from app.models import MemoryInjectionMetric, Session


class TestMemoryInjectionMetric:
    """Tests for MemoryInjectionMetric model."""

    def test_model_creation(self):
        """Test basic model instantiation with required fields."""
        metric = MemoryInjectionMetric(
            external_id="task-123",
            project_id="summitflow",
            variant="BASELINE",
            mandates_count=5,
            guardrails_count=3,
            reference_count=2,
            total_tokens=150,
        )

        assert metric.external_id == "task-123"
        assert metric.project_id == "summitflow"
        assert metric.variant == "BASELINE"
        assert metric.mandates_count == 5
        assert metric.guardrails_count == 3
        assert metric.reference_count == 2
        assert metric.total_tokens == 150

    def test_model_defaults(self):
        """Test that default values are defined in the model schema.

        Note: SQLAlchemy's Column(default=X) applies during INSERT, not on object creation.
        We verify the defaults are defined in the column schema.
        """
        # Get column defaults from the model's table
        table = MemoryInjectionMetric.__table__

        # Check numeric columns have defaults of 0
        assert table.c.mandates_count.default.arg == 0
        assert table.c.guardrails_count.default.arg == 0
        assert table.c.reference_count.default.arg == 0
        assert table.c.total_tokens.default.arg == 0
        assert table.c.retries.default.arg == 0

        # Check variant default
        assert table.c.variant.default.arg == "BASELINE"

        # Check JSON columns have defaults defined (callable defaults for mutable)
        assert table.c.memories_cited.default is not None
        assert table.c.memories_loaded.default is not None

    def test_model_with_all_fields(self):
        """Test model with all optional fields populated."""
        metric = MemoryInjectionMetric(
            session_id="sess-abc123",
            external_id="task-456",
            project_id="agent-hub",
            injection_latency_ms=45,
            mandates_count=10,
            guardrails_count=5,
            reference_count=8,
            total_tokens=350,
            query="pytest fixtures mock",
            variant="ENHANCED",
            task_succeeded=True,
            retries=1,
            memories_cited=["uuid-1", "uuid-2"],
            memories_loaded=["uuid-1", "uuid-2", "uuid-3", "uuid-4"],
        )

        assert metric.session_id == "sess-abc123"
        assert metric.injection_latency_ms == 45
        assert metric.query == "pytest fixtures mock"
        assert metric.task_succeeded is True
        assert metric.retries == 1
        assert metric.memories_cited == ["uuid-1", "uuid-2"]
        assert metric.memories_loaded == ["uuid-1", "uuid-2", "uuid-3", "uuid-4"]

    def test_tablename(self):
        """Test the model uses correct table name."""
        assert MemoryInjectionMetric.__tablename__ == "memory_injection_metrics"

    def test_session_relationship_defined(self):
        """Test that the relationship to Session is defined."""
        # Check the relationship is defined in the model's mapper
        relationships = MemoryInjectionMetric.__mapper__.relationships
        assert "session" in relationships

    def test_session_back_populates(self):
        """Test that Session model has back_populates for injection_metrics."""
        relationships = Session.__mapper__.relationships
        assert "injection_metrics" in relationships
