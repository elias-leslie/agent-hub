"""OpenTelemetry instrumentation for Agent Hub.

Provides distributed tracing with context propagation for:
- HTTP requests
- Subagent spawning and execution
- Cross-agent correlation
"""

import logging
import os
from contextvars import ContextVar
from typing import Any

from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.trace import Span, SpanKind, Status, StatusCode, Tracer

logger = logging.getLogger(__name__)

# Service name for this application
SERVICE_NAME = "agent-hub"
SERVICE_VERSION = "0.1.0"

# Context var for current subagent trace
_subagent_context: ContextVar[dict[str, str]] = ContextVar("subagent_context", default={})


def setup_telemetry(
    service_name: str = SERVICE_NAME,
    otlp_endpoint: str | None = None,
    console_export: bool = True,
) -> TracerProvider:
    """Initialize OpenTelemetry with tracing.

    Args:
        service_name: Name of this service for traces.
        otlp_endpoint: OTLP collector endpoint (e.g., http://localhost:4317).
            If None, uses OTEL_EXPORTER_OTLP_ENDPOINT env var or console export.
        console_export: Whether to also export to console for debugging.

    Returns:
        Configured TracerProvider.
    """
    # Create resource with service metadata
    resource = Resource.create(
        {
            "service.name": service_name,
            "service.version": SERVICE_VERSION,
        }
    )

    # Create tracer provider
    provider = TracerProvider(resource=resource)

    # Add console exporter for development
    if console_export:
        provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))

    # Add OTLP exporter if configured
    endpoint = otlp_endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter,
            )

            otlp_exporter = OTLPSpanExporter(endpoint=endpoint)
            provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
            logger.info(f"OTLP tracing enabled: {endpoint}")
        except ImportError:
            logger.warning("OTLP exporter not available, using console only")

    # Set as global provider
    trace.set_tracer_provider(provider)
    logger.info(f"Telemetry initialized for {service_name}")

    return provider


def get_tracer(name: str = __name__) -> Tracer:
    """Get a tracer for creating spans.

    Args:
        name: Module or component name for the tracer.

    Returns:
        OpenTelemetry Tracer instance.
    """
    return trace.get_tracer(name, SERVICE_VERSION)


def get_current_trace_id() -> str | None:
    """Get the current trace ID from context.

    Returns:
        Hex string trace ID or None if no active trace.
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        if ctx.is_valid:
            return format(ctx.trace_id, "032x")
    return None


def get_current_span_id() -> str | None:
    """Get the current span ID from context.

    Returns:
        Hex string span ID or None if no active span.
    """
    span = trace.get_current_span()
    if span and span.is_recording():
        ctx = span.get_span_context()
        if ctx.is_valid:
            return format(ctx.span_id, "016x")
    return None


def create_subagent_context() -> dict[str, str]:
    """Create context headers for propagating trace to subagent.

    Call this from the parent agent before spawning a subagent.
    The returned dict contains W3C Trace Context headers.

    Returns:
        Dict with traceparent/tracestate headers.
    """
    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


def extract_subagent_context(carrier: dict[str, str]) -> Context:
    """Extract trace context from carrier headers.

    Call this in the subagent to restore parent's trace context.

    Args:
        carrier: Dict with traceparent/tracestate headers.

    Returns:
        OpenTelemetry Context with parent span info.
    """
    return extract(carrier)


def start_subagent_span(
    name: str,
    subagent_id: str,
    parent_context: dict[str, str] | None = None,
    attributes: dict[str, Any] | None = None,
) -> Span:
    """Start a new span for subagent execution.

    Args:
        name: Subagent name or description.
        subagent_id: Unique ID for this subagent instance.
        parent_context: Context headers from parent (if any).
        attributes: Additional span attributes.

    Returns:
        Started Span (use as context manager or call end()).
    """
    tracer = get_tracer("agent-hub.orchestration")

    # Extract parent context if provided
    ctx = None
    if parent_context:
        ctx = extract_subagent_context(parent_context)

    # Build attributes
    span_attrs = {
        "subagent.id": subagent_id,
        "subagent.name": name,
    }
    if attributes:
        span_attrs.update(attributes)

    # Start span with parent context
    span = tracer.start_span(
        f"subagent:{name}",
        context=ctx,
        kind=SpanKind.INTERNAL,
        attributes=span_attrs,
    )

    return span


def end_subagent_span(
    span: Span,
    status: str,
    error: str | None = None,
    tokens_used: int = 0,
) -> None:
    """End a subagent span with status.

    Args:
        span: The span to end.
        status: Subagent execution status (completed, error, timeout).
        error: Error message if failed.
        tokens_used: Total tokens consumed.
    """
    span.set_attribute("subagent.status", status)
    span.set_attribute("subagent.tokens_used", tokens_used)

    if error:
        span.set_attribute("error.message", error)
        span.set_status(Status(StatusCode.ERROR, error))
    elif status == "completed":
        span.set_status(Status(StatusCode.OK))
    else:
        span.set_status(Status(StatusCode.ERROR, f"Status: {status}"))

    span.end()


class SubagentTraceContext:
    """Context manager for traced subagent execution.

    Usage:
        with SubagentTraceContext("analyzer", "abc123") as ctx:
            # Execute subagent
            result = await subagent.run()
            ctx.set_tokens(result.tokens)
    """

    def __init__(
        self,
        name: str,
        subagent_id: str,
        parent_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
    ):
        self.name = name
        self.subagent_id = subagent_id
        self.parent_id = parent_id
        self.provider = provider
        self.model = model
        self._span: Span | None = None
        self._tokens = 0

    def __enter__(self) -> "SubagentTraceContext":
        tracer = get_tracer("agent-hub.orchestration")

        attrs = {
            "subagent.id": self.subagent_id,
            "subagent.name": self.name,
        }
        if self.parent_id:
            attrs["subagent.parent_id"] = self.parent_id
        if self.provider:
            attrs["subagent.provider"] = self.provider
        if self.model:
            attrs["subagent.model"] = self.model

        self._span = tracer.start_span(
            f"subagent:{self.name}",
            kind=SpanKind.INTERNAL,
            attributes=attrs,
        )
        return self

    def __exit__(self, exc_type: type | None, exc_val: Exception | None, exc_tb: Any) -> None:
        if self._span:
            self._span.set_attribute("subagent.tokens_used", self._tokens)
            if exc_val:
                self._span.set_attribute("error.message", str(exc_val))
                self._span.set_status(Status(StatusCode.ERROR, str(exc_val)))
            else:
                self._span.set_status(Status(StatusCode.OK))
            self._span.end()

    def set_tokens(self, tokens: int) -> None:
        """Set tokens used by this subagent."""
        self._tokens = tokens

    def set_status(self, status: str, error: str | None = None) -> None:
        """Set execution status."""
        if self._span:
            self._span.set_attribute("subagent.status", status)
            if error:
                self._span.set_attribute("error.message", error)

    @property
    def trace_id(self) -> str | None:
        """Get trace ID for this span."""
        if self._span:
            ctx = self._span.get_span_context()
            if ctx.is_valid:
                return format(ctx.trace_id, "032x")
        return None


# Module-level tracer provider (initialized lazily)
_provider: TracerProvider | None = None


def init_telemetry() -> TracerProvider:
    """Initialize telemetry if not already initialized.

    Returns:
        The TracerProvider.
    """
    global _provider
    if _provider is None:
        _provider = setup_telemetry(
            console_export=os.environ.get("OTEL_CONSOLE_EXPORT", "true").lower() == "true"
        )
    return _provider
