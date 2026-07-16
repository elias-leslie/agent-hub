"""Universal LLM types.

Direct Python port of pi-mono ``packages/ai/src/types.ts`` (SHA 3d9e14d7).
See ``backend/tasks/agent-framework-convergence/`` for the convergence
contract: every adapter speaks ONLY these types.

Mapping notes (per convergence-map.md D10):

* TS ``interface`` → ``@dataclass(slots=True)`` (Pydantic only at HTTP boundary).
* TS discriminated union → Python PEP 604 union with a ``Literal`` discriminator.
* TS ``AbortSignal`` → ``asyncio.Event`` (the cancellation primitive already in use).
* Vocabulary names preserved verbatim: ``AssistantMessageEvent``, ``StreamOptions``,
  ``SimpleStreamOptions``, ``Context``, ``Tool``, ``Usage``, ``StopReason``,
  ``Model``, ``ApiProvider``. Method/file names: snake_case.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, TypeVar

if TYPE_CHECKING:
    from .event_stream import AssistantMessageEventStream
    from .utils.diagnostics import AssistantMessageDiagnostic


# ---------------------------------------------------------------------------
# API / provider identifiers
# ---------------------------------------------------------------------------

KnownApi = Literal[
    "openai-completions",
    "mistral-conversations",
    "openai-responses",
    "azure-openai-responses",
    "openai-codex-responses",
    "anthropic-messages",
    "bedrock-converse-stream",
    "google-generative-ai",
    "google-vertex",
]
"""Known API surface identifiers. Foreign strings are accepted via ``Api = str``."""

Api = str
"""Open string: ``KnownApi`` values are preferred but any string is valid."""

KnownImagesApi = Literal["openrouter-images"]
ImagesApi = str

KnownProvider = Literal[
    "amazon-bedrock",
    "anthropic",
    "google",
    "google-vertex",
    "openai",
    "azure-openai-responses",
    "openai-codex",
    "deepseek",
    "github-copilot",
    "xai",
    "groq",
    "cerebras",
    "openrouter",
    "vercel-ai-gateway",
    "zai",
    "mistral",
    "minimax",
    "minimax-cn",
    "moonshotai",
    "moonshotai-cn",
    "huggingface",
    "fireworks",
    "together",
    "opencode",
    "opencode-go",
    "kimi-coding",
    "cloudflare-workers-ai",
    "cloudflare-ai-gateway",
    "xiaomi",
    "xiaomi-token-plan-cn",
    "xiaomi-token-plan-ams",
    "xiaomi-token-plan-sgp",
]
Provider = str

KnownImagesProvider = Literal["openrouter"]
ImagesProvider = str


# ---------------------------------------------------------------------------
# Thinking levels
# ---------------------------------------------------------------------------

ThinkingLevel = Literal["minimal", "low", "medium", "high", "xhigh"]
ModelThinkingLevel = Literal["off", "minimal", "low", "medium", "high", "xhigh"]
ThinkingLevelMap = dict[ModelThinkingLevel, str | None]


@dataclass(slots=True)
class ThinkingBudgets:
    """Token budgets for each thinking level (token-based providers only)."""

    minimal: int | None = None
    low: int | None = None
    medium: int | None = None
    high: int | None = None


# ---------------------------------------------------------------------------
# Base stream options
# ---------------------------------------------------------------------------

CacheRetention = Literal["none", "short", "long"]
Transport = Literal["sse", "websocket", "websocket-cached", "auto"]


@dataclass(slots=True)
class ProviderResponse:
    status: int
    headers: dict[str, str]


# Payload/response callback aliases. Async or sync; payloads may be replaced
# by returning a value (return ``None`` to keep the payload unchanged).
PayloadCallback = Callable[[Any, "Model[Any]"], Any | Awaitable[Any] | None]
ResponseCallback = Callable[[ProviderResponse, "Model[Any]"], None | Awaitable[None]]


@dataclass(slots=True)
class StreamOptions:
    """Base options every provider accepts.

    ``signal`` is pi-mono's ``AbortSignal``. In Python we use an ``asyncio.Event``;
    providers ``set()`` is checked between iterations and surfaces as a stop
    reason of ``"aborted"``.
    """

    temperature: float | None = None
    max_tokens: int | None = None
    signal: asyncio.Event | None = None
    api_key: str | None = None
    transport: Transport | None = None
    cache_retention: CacheRetention | None = None
    session_id: str | None = None
    on_payload: PayloadCallback | None = None
    on_response: ResponseCallback | None = None
    headers: dict[str, str] | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None
    max_retry_delay_ms: int | None = None
    metadata: dict[str, Any] | None = None


@dataclass(slots=True)
class SimpleStreamOptions(StreamOptions):
    """Unified options with reasoning passed to ``stream_simple``/``complete_simple``."""

    reasoning: ThinkingLevel | None = None
    thinking_budgets: ThinkingBudgets | None = None


# ProviderStreamOptions in pi-mono is ``StreamOptions & Record<string, unknown>``.
# In Python, provider subclasses extend ``StreamOptions`` with their own fields;
# the base type alias is exposed for callers that don't care about the variant.
ProviderStreamOptions = StreamOptions


@dataclass(slots=True)
class ImagesOptions:
    signal: asyncio.Event | None = None
    api_key: str | None = None
    on_payload: PayloadCallback | None = None
    on_response: ResponseCallback | None = None
    headers: dict[str, str] | None = None
    timeout_ms: int | None = None
    max_retries: int | None = None
    max_retry_delay_ms: int | None = None
    metadata: dict[str, Any] | None = None


ProviderImagesOptions = ImagesOptions


# ---------------------------------------------------------------------------
# Content blocks
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class TextSignatureV1:
    """Tagged text-signature payload, used for OpenAI Responses message metadata."""

    v: Literal[1] = 1
    id: str = ""
    phase: Literal["commentary", "final_answer"] | None = None


@dataclass(slots=True)
class TextContent:
    text: str
    type: Literal["text"] = "text"
    # OpenAI Responses message metadata: legacy id string or TextSignatureV1 JSON.
    text_signature: str | None = None


@dataclass(slots=True)
class ThinkingContent:
    thinking: str
    type: Literal["thinking"] = "thinking"
    # OpenAI Responses: reasoning item ID.
    thinking_signature: str | None = None
    # When true, ``thinking`` is empty and ``thinking_signature`` holds the opaque
    # encrypted payload to pass back for multi-turn continuity.
    redacted: bool = False


@dataclass(slots=True)
class ImageContent:
    data: str  # base64-encoded image data
    mime_type: str  # e.g. "image/jpeg", "image/png"
    type: Literal["image"] = "image"


@dataclass(slots=True)
class AudioContent:
    data: str  # base64-encoded audio data
    mime_type: str  # e.g. "audio/wav", "audio/mpeg"
    type: Literal["audio"] = "audio"


@dataclass(slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]
    type: Literal["toolCall"] = "toolCall"
    # Google-specific: opaque signature for reusing thought context.
    thought_signature: str | None = None


# ---------------------------------------------------------------------------
# Usage / stop reason
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class UsageCost:
    input: float = 0.0
    output: float = 0.0
    cache_read: float = 0.0
    cache_write: float = 0.0
    total: float = 0.0


@dataclass(slots=True)
class Usage:
    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    total_tokens: int = 0
    cost: UsageCost = field(default_factory=UsageCost)


StopReason = Literal["stop", "length", "toolUse", "error", "aborted"]
"""The locked 5-value enum (D2). Provider-specific reasons map to ``error``/``length``."""


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

UserContent = TextContent | ImageContent | AudioContent
AssistantContent = TextContent | ThinkingContent | ToolCall
ToolResultContent = TextContent | ImageContent


@dataclass(slots=True)
class UserMessage:
    content: str | list[UserContent]
    timestamp: int  # Unix ms
    role: Literal["user"] = "user"


@dataclass(slots=True)
class AssistantMessage:
    content: list[AssistantContent]
    api: Api
    provider: Provider
    model: str
    usage: Usage
    stop_reason: StopReason
    timestamp: int  # Unix ms
    role: Literal["assistant"] = "assistant"
    # Concrete chunk.model when different from the requested model
    # (e.g. OpenRouter ``auto`` -> ``anthropic/...``).
    response_model: str | None = None
    # Provider-specific response/message identifier when the upstream API exposes one.
    response_id: str | None = None
    # Redacted provider/runtime diagnostics for failures and recoveries.
    diagnostics: list[AssistantMessageDiagnostic] | None = None
    error_message: str | None = None


@dataclass(slots=True)
class ToolResultMessage:
    tool_call_id: str
    tool_name: str
    content: list[ToolResultContent]
    is_error: bool
    timestamp: int  # Unix ms
    role: Literal["toolResult"] = "toolResult"
    # Generic provider/runtime details. See D5: ``details={"container": {...}}``
    # carries sandboxed-tool execution state.
    details: dict[str, Any] | None = None


Message = UserMessage | AssistantMessage | ToolResultMessage


# ---------------------------------------------------------------------------
# Images output
# ---------------------------------------------------------------------------

ImagesInputContent = TextContent | ImageContent
ImagesOutputContent = TextContent | ImageContent


@dataclass(slots=True)
class ImagesContext:
    input: list[ImagesInputContent]


ImagesStopReason = Literal["stop", "error", "aborted"]


@dataclass(slots=True)
class AssistantImages:
    api: ImagesApi
    provider: ImagesProvider
    model: str
    output: list[ImagesOutputContent]
    stop_reason: ImagesStopReason
    timestamp: int  # Unix ms
    response_id: str | None = None
    usage: Usage | None = None
    error_message: str | None = None


# ---------------------------------------------------------------------------
# Tool / Context
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Tool:
    """Universal tool definition.

    ``parameters`` is a JSON Schema object (dict). Validation/coercion lives
    in ``backend/app/llm/utils/validation.py``.
    """

    name: str
    description: str
    parameters: dict[str, Any]


@dataclass(slots=True)
class Context:
    messages: list[Message]
    system_prompt: str | None = None
    tools: list[Tool] | None = None


# ---------------------------------------------------------------------------
# Stream event protocol (12-variant discriminated union)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class StartEvent:
    partial: AssistantMessage
    type: Literal["start"] = "start"


@dataclass(slots=True)
class TextStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["text_start"] = "text_start"


@dataclass(slots=True)
class TextDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["text_delta"] = "text_delta"


@dataclass(slots=True)
class TextEndEvent:
    content_index: int
    content: str
    partial: AssistantMessage
    type: Literal["text_end"] = "text_end"


@dataclass(slots=True)
class ThinkingStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["thinking_start"] = "thinking_start"


@dataclass(slots=True)
class ThinkingDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["thinking_delta"] = "thinking_delta"


@dataclass(slots=True)
class ThinkingEndEvent:
    content_index: int
    content: str
    partial: AssistantMessage
    type: Literal["thinking_end"] = "thinking_end"


@dataclass(slots=True)
class ToolCallStartEvent:
    content_index: int
    partial: AssistantMessage
    type: Literal["toolcall_start"] = "toolcall_start"


@dataclass(slots=True)
class ToolCallDeltaEvent:
    content_index: int
    delta: str
    partial: AssistantMessage
    type: Literal["toolcall_delta"] = "toolcall_delta"


@dataclass(slots=True)
class ToolCallEndEvent:
    content_index: int
    tool_call: ToolCall
    partial: AssistantMessage
    type: Literal["toolcall_end"] = "toolcall_end"


DoneReason = Literal["stop", "length", "toolUse"]
ErrorReason = Literal["aborted", "error"]


@dataclass(slots=True)
class DoneEvent:
    reason: DoneReason
    message: AssistantMessage
    type: Literal["done"] = "done"


@dataclass(slots=True)
class ErrorEvent:
    reason: ErrorReason
    error: AssistantMessage
    type: Literal["error"] = "error"


AssistantMessageEvent = (
    StartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextEndEvent
    | ThinkingStartEvent
    | ThinkingDeltaEvent
    | ThinkingEndEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | DoneEvent
    | ErrorEvent
)


# ---------------------------------------------------------------------------
# Stream function signatures
# ---------------------------------------------------------------------------

TApi = TypeVar("TApi", bound=str)
TOptions = TypeVar("TOptions", bound=StreamOptions)

StreamFunction = Callable[..., "AssistantMessageEventStream"]
"""``(model, context, options=None) -> AssistantMessageEventStream``.

Once invoked, request/model/runtime failures must be encoded in the returned
stream — not thrown. Error termination produces an ``AssistantMessage`` with
``stop_reason`` ``"error"`` or ``"aborted"`` (plus ``error_message``), emitted
via the stream protocol.
"""

ImagesFunction = Callable[..., Awaitable[AssistantImages]]


# ---------------------------------------------------------------------------
# Compatibility overrides (D10: faithful copy of pi-mono shape)
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class OpenRouterMaxPrice:
    prompt: float | str | None = None
    completion: float | str | None = None
    image: float | str | None = None
    audio: float | str | None = None
    request: float | str | None = None


@dataclass(slots=True)
class OpenRouterThroughputBucket:
    p50: float | None = None
    p75: float | None = None
    p90: float | None = None
    p99: float | None = None


@dataclass(slots=True)
class OpenRouterSort:
    by: str | None = None
    partition: str | None = None


@dataclass(slots=True)
class OpenRouterRouting:
    """Routing preferences for OpenRouter (sent as the ``provider`` field).

    https://openrouter.ai/docs/guides/routing/provider-selection
    """

    allow_fallbacks: bool | None = None
    require_parameters: bool | None = None
    data_collection: Literal["deny", "allow"] | None = None
    zdr: bool | None = None
    enforce_distillable_text: bool | None = None
    order: list[str] | None = None
    only: list[str] | None = None
    ignore: list[str] | None = None
    quantizations: list[str] | None = None
    sort: str | OpenRouterSort | None = None
    max_price: OpenRouterMaxPrice | None = None
    preferred_min_throughput: float | OpenRouterThroughputBucket | None = None
    preferred_max_latency: float | OpenRouterThroughputBucket | None = None


@dataclass(slots=True)
class VercelGatewayRouting:
    only: list[str] | None = None
    order: list[str] | None = None


ThinkingFormat = Literal[
    "openai",
    "openrouter",
    "deepseek",
    "together",
    "zai",
    "qwen",
    "qwen-chat-template",
]


@dataclass(slots=True)
class OpenAICompletionsCompat:
    """Compatibility settings for OpenAI-compatible completions APIs."""

    supports_store: bool | None = None
    supports_developer_role: bool | None = None
    supports_reasoning_effort: bool | None = None
    supports_usage_in_streaming: bool | None = None
    max_tokens_field: Literal["max_completion_tokens", "max_tokens"] | None = None
    requires_tool_result_name: bool | None = None
    requires_assistant_after_tool_result: bool | None = None
    requires_thinking_as_text: bool | None = None
    requires_reasoning_content_on_assistant_messages: bool | None = None
    thinking_format: ThinkingFormat | None = None
    open_router_routing: OpenRouterRouting | None = None
    vercel_gateway_routing: VercelGatewayRouting | None = None
    zai_tool_stream: bool | None = None
    supports_strict_mode: bool | None = None
    cache_control_format: Literal["anthropic"] | None = None
    send_session_affinity_headers: bool | None = None
    supports_long_cache_retention: bool | None = None


@dataclass(slots=True)
class OpenAIResponsesCompat:
    """Compatibility settings for OpenAI Responses APIs."""

    send_session_id_header: bool | None = None
    supports_long_cache_retention: bool | None = None


@dataclass(slots=True)
class AnthropicMessagesCompat:
    """Compatibility settings for Anthropic Messages-compatible APIs."""

    supports_eager_tool_input_streaming: bool | None = None
    supports_long_cache_retention: bool | None = None
    send_session_affinity_headers: bool | None = None
    supports_cache_control_on_tools: bool | None = None


Compat = OpenAICompletionsCompat | OpenAIResponsesCompat | AnthropicMessagesCompat


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ModelCost:
    input: float  # $/million tokens
    output: float
    cache_read: float
    cache_write: float


@dataclass(slots=True)
class Model[TApi: str]:
    """Universal model descriptor.

    Catalog ``backend/app/constants/catalog_entries.py`` lives outside this
    package; the adapter boundary always sees a ``Model`` instance.
    """

    id: str
    name: str
    api: TApi
    provider: Provider
    base_url: str
    reasoning: bool
    input: list[Literal["text", "image", "audio"]]
    cost: ModelCost
    context_window: int
    max_tokens: int
    # Optional fields
    thinking_level_map: ThinkingLevelMap | None = None
    headers: dict[str, str] | None = None
    compat: Compat | None = None


@dataclass(slots=True)
class ImagesModel[TApi: str]:
    """Image-generation model descriptor."""

    id: str
    name: str
    api: TApi
    provider: ImagesProvider
    base_url: str
    input: list[Literal["text", "image"]]
    output: list[Literal["text", "image"]]
    cost: ModelCost
    headers: dict[str, str] | None = None


__all__ = [
    "AnthropicMessagesCompat",
    "Api",
    "AssistantContent",
    "AssistantImages",
    "AssistantMessage",
    "AssistantMessageEvent",
    "AudioContent",
    "CacheRetention",
    "Compat",
    "Context",
    "DoneEvent",
    "DoneReason",
    "ErrorEvent",
    "ErrorReason",
    "ImageContent",
    "ImagesApi",
    "ImagesContext",
    "ImagesFunction",
    "ImagesInputContent",
    "ImagesModel",
    "ImagesOptions",
    "ImagesOutputContent",
    "ImagesProvider",
    "ImagesStopReason",
    "KnownApi",
    "KnownImagesApi",
    "KnownImagesProvider",
    "KnownProvider",
    "Message",
    "Model",
    "ModelCost",
    "ModelThinkingLevel",
    "OpenAICompletionsCompat",
    "OpenAIResponsesCompat",
    "OpenRouterMaxPrice",
    "OpenRouterRouting",
    "OpenRouterSort",
    "OpenRouterThroughputBucket",
    "PayloadCallback",
    "Provider",
    "ProviderImagesOptions",
    "ProviderResponse",
    "ProviderStreamOptions",
    "ResponseCallback",
    "SimpleStreamOptions",
    "StartEvent",
    "StopReason",
    "StreamFunction",
    "StreamOptions",
    "TApi",
    "TOptions",
    "TextContent",
    "TextDeltaEvent",
    "TextEndEvent",
    "TextSignatureV1",
    "TextStartEvent",
    "ThinkingBudgets",
    "ThinkingContent",
    "ThinkingDeltaEvent",
    "ThinkingEndEvent",
    "ThinkingFormat",
    "ThinkingLevel",
    "ThinkingLevelMap",
    "ThinkingStartEvent",
    "Tool",
    "ToolCall",
    "ToolCallDeltaEvent",
    "ToolCallEndEvent",
    "ToolCallStartEvent",
    "ToolResultContent",
    "ToolResultMessage",
    "Transport",
    "Usage",
    "UsageCost",
    "UserContent",
    "UserMessage",
    "VercelGatewayRouting",
]
