"""Tests for telemetry module."""

from app.services.telemetry import (
    SubagentTraceContext,
    get_current_span_id,
    get_current_trace_id,
    get_tracer,
    init_telemetry,
    setup_telemetry,
)


class TestTelemetrySetup:
    """Tests for telemetry setup."""

    def test_setup_telemetry(self):
        """Test telemetry setup creates provider."""
        provider = setup_telemetry(
            service_name="test-service",
            console_export=False,
        )

        assert provider is not None

    def test_get_tracer(self):
        """Test getting a tracer."""
        tracer = get_tracer("test.module")
        assert tracer is not None

    def test_get_tracer_default_name(self):
        """Test getting tracer with default name."""
        tracer = get_tracer()
        assert tracer is not None


class TestTraceContext:
    """Tests for trace context functions."""

    def test_get_current_trace_id_no_span(self):
        """Test getting trace ID with no active span."""
        trace_id = get_current_trace_id()
        # May be None if no span is active
        assert trace_id is None or isinstance(trace_id, str)

    def test_get_current_span_id_no_span(self):
        """Test getting span ID with no active span."""
        span_id = get_current_span_id()
        assert span_id is None or isinstance(span_id, str)

    def test_get_trace_id_with_span(self):
        """Test getting trace ID with active span."""
        tracer = get_tracer("test")

        with tracer.start_as_current_span("test-span"):
            trace_id = get_current_trace_id()
            # Should have a valid trace ID
            assert trace_id is not None
            assert len(trace_id) == 32  # Hex format

    def test_get_span_id_with_span(self):
        """Test getting span ID with active span."""
        tracer = get_tracer("test")

        with tracer.start_as_current_span("test-span"):
            span_id = get_current_span_id()
            # Should have a valid span ID
            assert span_id is not None
            assert len(span_id) == 16  # Hex format


class TestSubagentTraceContext:
    """Tests for SubagentTraceContext context manager."""

    def test_context_manager_basic(self):
        """Test basic context manager usage."""
        with SubagentTraceContext("test-agent", "abc123") as ctx:
            assert ctx.name == "test-agent"
            assert ctx.subagent_id == "abc123"

    def test_context_manager_with_attrs(self):
        """Test context manager with attributes."""
        with SubagentTraceContext(
            name="analyzer",
            subagent_id="xyz789",
            parent_id="parent123",
            provider="claude",
            model="claude-sonnet-4-5",
        ) as ctx:
            assert ctx.parent_id == "parent123"
            assert ctx.provider == "claude"
            assert ctx.model == "claude-sonnet-4-5"

    def test_set_tokens(self):
        """Test setting tokens in context."""
        with SubagentTraceContext("test", "abc") as ctx:
            ctx.set_tokens(1000)
            assert ctx._tokens == 1000

    def test_set_status(self):
        """Test setting status in context."""
        with SubagentTraceContext("test", "abc") as ctx:
            ctx.set_status("completed")
            # No assertion - just verify no error

    def test_set_status_with_error(self):
        """Test setting error status in context."""
        with SubagentTraceContext("test", "abc") as ctx:
            ctx.set_status("error", error="Something failed")
            # No assertion - just verify no error

    def test_trace_id_property(self):
        """Test trace_id property."""
        with SubagentTraceContext("test", "abc") as ctx:
            # Trace ID may be None if span is not recording
            trace_id = ctx.trace_id
            # Just verify property works
            assert trace_id is None or isinstance(trace_id, str)

    def test_exception_handling(self):
        """Test context handles exceptions properly."""
        try:
            with SubagentTraceContext("test", "abc"):
                raise ValueError("Test error")
        except ValueError:
            pass  # Expected

    def test_nested_contexts(self):
        """Test nested trace contexts."""
        with SubagentTraceContext("parent", "p123") as parent:
            parent.set_tokens(500)
            with SubagentTraceContext("child", "c456", parent_id="p123") as child:
                child.set_tokens(200)
                assert child.parent_id == "p123"


class TestInitTelemetry:
    """Tests for lazy initialization."""

    def test_init_telemetry_idempotent(self):
        """Test init_telemetry is idempotent."""
        provider1 = init_telemetry()
        provider2 = init_telemetry()

        # Should return same provider
        assert provider1 is provider2
