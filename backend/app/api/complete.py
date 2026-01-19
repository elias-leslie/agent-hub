"""Completion API endpoint."""

import json
import logging
import uuid
from typing import Annotated, Any

import jsonschema
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    Message,
    ProviderError,
    RateLimitError,
)
from app.adapters.claude import ClaudeAdapter
from app.adapters.gemini import GeminiAdapter
from app.constants import DEFAULT_OUTPUT_LIMIT
from app.db import get_db
from app.models import Message as DBMessage
from app.models import Session as DBSession
from app.models import TruncationEvent

# NOTE: Auto-compression removed per Anthropic harness architecture guidance.
# Context management belongs in the harness (SummitFlow), not the API layer.
# Agent Hub provides token tracking and warnings; the caller decides when to
# checkpoint and restart. See: anthropic.com/engineering/effective-harnesses-for-long-running-agents
from app.services.context_tracker import (
    check_context_before_request,
    log_token_usage,
    should_emit_warning,
)
from app.services.events import (
    publish_complete,
    publish_error,
    publish_message,
    publish_session_start,
)
from app.services.memory import (
    extract_uuid_prefixes,
    inject_progressive_context,
    parse_memory_group_id,
    resolve_full_uuids,
    track_loaded_batch,
    track_referenced_batch,
)
from app.services.response_cache import get_response_cache
from app.services.token_counter import (
    build_output_usage,
    count_message_tokens,
    estimate_cost,
    estimate_request,
    validate_max_tokens,
)

logger = logging.getLogger(__name__)

router = APIRouter()


def validate_json_response(content: str, schema: dict[str, Any]) -> tuple[bool, str | None]:
    """Validate JSON response against a JSON Schema.

    Args:
        content: The response content (should be valid JSON).
        schema: The JSON Schema to validate against.

    Returns:
        Tuple of (is_valid, error_message). If valid, error_message is None.
    """
    try:
        # Parse the JSON content
        parsed = json.loads(content)
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"

    try:
        # Validate against schema
        jsonschema.validate(instance=parsed, schema=schema)
        return True, None
    except jsonschema.ValidationError as e:
        return False, f"Schema validation failed: {e.message}"


# Request/Response schemas
class MessageInput(BaseModel):
    """Input message in conversation.

    Content can be:
    - str: Simple text content
    - list[dict]: Content blocks for vision (text + image)

    Image block format:
    {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": "image/png",
            "data": "<base64-encoded-data>"
        }
    }
    """

    role: str = Field(..., description="Message role: user, assistant, or system")
    content: str | list[dict[str, Any]] = Field(
        ..., description="Message content - string or list of content blocks"
    )


class ToolDefinition(BaseModel):
    """Tool definition for model to call."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(..., description="JSON Schema for tool parameters")
    allowed_callers: list[str] = Field(
        default=["direct"],
        description="Who can call this tool: direct, code_execution_20250825",
    )


class ResponseFormat(BaseModel):
    """Response format specification for structured output (JSON mode)."""

    type: str = Field(
        default="text",
        description="Output type: 'text' (default) or 'json_object' for JSON mode",
    )
    schema_: dict[str, Any] | None = Field(
        default=None,
        alias="schema",
        description="JSON Schema for validating structured output (optional)",
    )

    model_config = {"populate_by_name": True}


class RoutingConfig(BaseModel):
    """Configuration for capability-based model routing.

    Instead of specifying a model directly, consumers can request a capability
    and let the routing layer select the appropriate model.
    """

    capability: str | None = Field(
        default=None,
        description=(
            "Model capability to use: coding, planning, review, fast_task, "
            "worker, supervisor_primary, supervisor_audit. "
            "If provided, overrides the model field."
        ),
    )
    provider_preference: str | None = Field(
        default=None,
        description="Prefer a specific provider: 'claude' or 'gemini'. Optional.",
    )
    is_autonomous: bool = Field(
        default=False,
        description=(
            "Whether this is an autonomous agent operation. "
            "If true, safety directives are injected into the system prompt."
        ),
    )


class CompletionRequest(BaseModel):
    """Request body for completion endpoint."""

    model: str = Field(..., description="Model identifier (e.g., claude-sonnet-4-5-20250514)")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    max_tokens: int = Field(
        default=DEFAULT_OUTPUT_LIMIT, ge=1, le=100000, description="Max tokens in response"
    )
    temperature: float = Field(default=1.0, ge=0.0, le=2.0, description="Sampling temperature")
    session_id: str | None = Field(default=None, description="Existing session ID to continue")
    project_id: str = Field(..., description="Project ID for session tracking (required)")
    purpose: str | None = Field(
        default=None,
        description="Purpose of this session (task_enrichment, code_generation, etc.)",
    )
    external_id: str | None = Field(
        default=None,
        description="External ID for cost aggregation (e.g., task-123, user-456)",
    )
    enable_caching: bool = Field(default=True, description="Enable prompt caching (Claude only)")
    cache_ttl: str = Field(default="ephemeral", description="Cache TTL: ephemeral (5min) or 1h")
    # Structured output (JSON mode) support
    response_format: ResponseFormat | None = Field(
        default=None,
        description="Response format: {type: 'json_object', schema: {...}} for JSON mode",
    )
    # Extended Thinking support (provider-agnostic)
    thinking_level: str | None = Field(
        default=None,
        pattern="^(minimal|low|medium|high|ultrathink)$",
        description=(
            "Thinking depth level: minimal (Flash only), low, medium, high, ultrathink. "
            "Provider-agnostic - mapped to provider-specific params internally."
        ),
    )
    auto_thinking: bool = Field(
        default=False,
        description="Auto-enable thinking for complex requests",
    )
    # Tool calling support
    tools: list[ToolDefinition] | None = Field(
        default=None,
        description="Tool definitions for model to call",
    )
    enable_programmatic_tools: bool = Field(
        default=False,
        description="Enable code execution to call tools programmatically (Claude only)",
    )
    container_id: str | None = Field(
        default=None,
        description="Container ID for code execution continuity (Claude only)",
    )
    # Memory injection
    use_memory: bool = Field(
        default=False,
        description="Inject relevant context from knowledge graph memory",
    )
    memory_group_id: str | None = Field(
        default=None,
        description="Memory group ID for isolation (defaults to project_id)",
    )
    # Capability-based routing
    routing_config: RoutingConfig | None = Field(
        default=None,
        description=(
            "Capability-based model routing. If routing_config.capability is set, "
            "it overrides the model field to select an appropriate model for the capability."
        ),
    )


class CacheInfo(BaseModel):
    """Cache usage information."""

    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_hit_rate: float = 0.0


class UsageInfo(BaseModel):
    """Token usage information."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cache: CacheInfo | None = None


class ContextUsageInfo(BaseModel):
    """Context window usage information."""

    used_tokens: int = Field(..., description="Tokens currently in context")
    limit_tokens: int = Field(..., description="Model's context window limit")
    percent_used: float = Field(..., description="Percentage of context used")
    remaining_tokens: int = Field(..., description="Tokens available")
    warning: str | None = Field(default=None, description="Warning if approaching limit")


class OutputUsageInfo(BaseModel):
    """Output token usage and truncation information."""

    output_tokens: int = Field(..., description="Actual tokens generated")
    max_tokens_requested: int = Field(..., description="max_tokens value used for request")
    model_limit: int = Field(..., description="Model's max output capability")
    was_truncated: bool = Field(
        ..., description="True if response was truncated (finish_reason=max_tokens)"
    )
    warning: str | None = Field(default=None, description="Truncation or validation warning")


class ThinkingInfo(BaseModel):
    """Extended thinking information."""

    content: str = Field(..., description="Thinking content from the model")
    tokens: int | None = Field(default=None, description="Tokens used for thinking")
    level_used: str | None = Field(default=None, description="Thinking level used")
    cost_usd: float | None = Field(default=None, description="Estimated cost of thinking in USD")


class ToolCallInfo(BaseModel):
    """Information about a tool call from the model."""

    id: str = Field(..., description="Unique ID for this tool call")
    name: str = Field(..., description="Tool name")
    input: dict[str, Any] = Field(..., description="Tool input parameters")
    caller_type: str = Field(
        default="direct", description="Who initiated: direct or code_execution"
    )
    caller_tool_id: str | None = Field(
        default=None, description="Tool ID if called from code execution"
    )


class ContainerInfo(BaseModel):
    """Container state for programmatic tool calling."""

    id: str = Field(..., description="Container ID for continuity")
    expires_at: str = Field(..., description="Container expiration timestamp")


class CompletionResponse(BaseModel):
    """Response body for completion endpoint."""

    content: str = Field(..., description="Generated content")
    model: str = Field(..., description="Model used for generation")
    provider: str = Field(..., description="Provider that served the request")
    usage: UsageInfo = Field(..., description="Token usage")
    context_usage: ContextUsageInfo | None = Field(default=None, description="Context window usage")
    output_usage: OutputUsageInfo | None = Field(
        default=None, description="Output token usage and truncation info"
    )
    session_id: str = Field(..., description="Session ID for continuing conversation")
    finish_reason: str | None = Field(default=None, description="Why generation stopped")
    from_cache: bool = Field(default=False, description="Whether response was served from cache")
    # Extended thinking (Claude only)
    thinking: ThinkingInfo | None = Field(default=None, description="Extended thinking content")
    # Tool calling (when model requests tool execution)
    tool_calls: list[ToolCallInfo] | None = Field(
        default=None,
        description="Tool calls requested by model (caller must execute and continue)",
    )
    container: ContainerInfo | None = Field(
        default=None,
        description="Container state for code execution continuity",
    )
    # Memory injection info
    memory_facts_injected: int = Field(
        default=0,
        description="Number of memory facts injected into context",
    )
    # Memory UUIDs for feedback attribution (comma-separated)
    memory_uuids: str | None = Field(
        default=None,
        description="Comma-separated UUIDs of injected memory items (for feedback attribution)",
    )


def _get_provider(model: str) -> str:
    """Determine provider from model name."""
    model_lower = model.lower()
    if "claude" in model_lower:
        return "claude"
    elif "gemini" in model_lower:
        return "gemini"
    else:
        # Default to claude for unknown models
        return "claude"


# Auto-thinking detection configuration
# Inspired by Claude Code UX: Tab toggle, "ultrathink" trigger, sticky state
# See: https://claudelog.com/faqs/how-to-toggle-thinking-in-claude-code/

# Keywords that suggest complex reasoning where thinking helps
_THINKING_TRIGGERS = [
    # Explicit thinking requests (Claude Code style)
    "ultrathink",  # Maximum budget trigger
    "think hard",
    "think carefully",
    "think step by step",
    # Analysis tasks
    "analyze",
    "evaluate",
    "compare",
    "explain why",
    # Reasoning tasks
    "reason",
    "think through",
    "consider carefully",
    # Code tasks
    "debug",
    "review code",
    "find the bug",
    "what's wrong",
    "refactor",
    # Complexity markers
    "multi-step",
    "complex",
    "edge cases",
]


def _extract_text_content(content: str | list[dict[str, Any]]) -> str:
    """Extract text content from message content.

    Args:
        content: String or list of content blocks.

    Returns:
        Extracted text content.
    """
    if isinstance(content, str):
        return content
    # Extract text from content blocks
    texts = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            texts.append(block.get("text", ""))
        elif isinstance(block, str):
            texts.append(block)
    return " ".join(texts)


def _should_enable_thinking(messages: list[Message]) -> bool:
    """Detect if request would benefit from extended thinking.

    Triggers on:
    - Explicit thinking keywords (ultrathink, think hard, etc.)
    - Keywords suggesting complex reasoning
    - Multi-step instructions (numbered lists)
    - Code review/analysis requests
    """
    # Check the last user message
    for msg in reversed(messages):
        if msg.role == "user":
            text_content = _extract_text_content(msg.content)
            content_lower = text_content.lower()
            for trigger in _THINKING_TRIGGERS:
                if trigger in content_lower:
                    return True
            # Also trigger on numbered steps (1. 2. 3.)
            if any(f"{i}." in text_content for i in range(1, 10)):
                return True
            break
    return False


# Cached adapter instances - created once, reused across requests
_adapter_cache: dict[str, ClaudeAdapter | GeminiAdapter] = {}


def _get_adapter(provider: str) -> ClaudeAdapter | GeminiAdapter:
    """Get cached adapter instance for provider."""
    if provider in _adapter_cache:
        return _adapter_cache[provider]

    if provider == "claude":
        adapter: ClaudeAdapter | GeminiAdapter = ClaudeAdapter()
    elif provider == "gemini":
        adapter = GeminiAdapter()
    else:
        raise ValueError(f"Unknown provider: {provider}")

    _adapter_cache[provider] = adapter
    logger.info(f"Created cached adapter for {provider}")
    return adapter


def clear_adapter_cache() -> None:
    """Clear the adapter cache. Useful for testing."""
    _adapter_cache.clear()


async def _get_or_create_session(
    db: AsyncSession,
    session_id: str | None,
    project_id: str,
    provider: str,
    model: str,
    purpose: str | None = None,
    session_type: str = "completion",
    external_id: str | None = None,
) -> tuple[DBSession, list[Message], bool]:
    """Get existing session or create new one. Returns (session, messages, is_new)."""
    if session_id:
        # Try to load existing session
        result = await db.execute(
            select(DBSession)
            .options(selectinload(DBSession.messages))
            .where(DBSession.id == session_id)
        )
        session = result.scalar_one_or_none()
        if session:
            # Load existing messages as context
            context_messages = [
                Message(role=m.role, content=m.content)  # type: ignore[arg-type]
                for m in sorted(session.messages, key=lambda x: x.created_at)
            ]
            return session, context_messages, False

    # Create new session
    new_session_id = session_id or str(uuid.uuid4())
    session = DBSession(
        id=new_session_id,
        project_id=project_id,
        provider=provider,
        model=model,
        status="active",
        purpose=purpose,
        session_type=session_type,
        external_id=external_id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session, [], True


async def _save_messages(
    db: AsyncSession,
    session_id: str,
    user_messages: list[MessageInput],
    assistant_content: str,
    input_tokens: int,
    output_tokens: int,
) -> None:
    """Save user messages and assistant response to database."""
    # Save user messages (only new ones - last message typically)
    for msg in user_messages:
        if msg.role in ("user", "system"):
            db_msg = DBMessage(
                session_id=session_id,
                role=msg.role,
                content=msg.content,
            )
            db.add(db_msg)

    # Save assistant response
    db_msg = DBMessage(
        session_id=session_id,
        role="assistant",
        content=assistant_content,
        tokens=output_tokens,
    )
    db.add(db_msg)
    await db.commit()


async def _update_provider_metadata(
    db: AsyncSession,
    session: DBSession,
    cache_metrics: dict[str, Any] | None,
) -> None:
    """Update session with provider-specific metadata like cache info."""
    if not cache_metrics:
        return

    # Merge with existing metadata
    existing = session.provider_metadata or {}
    existing["cache"] = {
        "last_cache_creation_tokens": cache_metrics.get("cache_creation_input_tokens", 0),
        "last_cache_read_tokens": cache_metrics.get("cache_read_input_tokens", 0),
        "total_cache_creation_tokens": existing.get("cache", {}).get(
            "total_cache_creation_tokens", 0
        )
        + cache_metrics.get("cache_creation_input_tokens", 0),
        "total_cache_read_tokens": existing.get("cache", {}).get("total_cache_read_tokens", 0)
        + cache_metrics.get("cache_read_input_tokens", 0),
    }
    session.provider_metadata = existing
    await db.commit()


@router.post("/complete", response_model=CompletionResponse)
async def complete(
    request: CompletionRequest,
    x_skip_cache: Annotated[str | None, Header(alias="X-Skip-Cache")] = None,
    db: Annotated[AsyncSession | None, Depends(get_db)] = None,
) -> CompletionResponse:
    """
    Generate a completion for the given messages.

    Routes to appropriate provider (Claude or Gemini) based on model name.
    Optionally persists messages to database for session continuity.

    Headers:
        X-Skip-Cache: Set to "true" to bypass response cache
    """
    # DEBUG: Log incoming request details
    import hashlib

    request_hash = hashlib.md5(
        f"{request.model}:{len(request.messages)}:{request.max_tokens}".encode()
    ).hexdigest()[:8]
    logger.info(
        f"DEBUG[{request_hash}] complete() called: model={request.model}, "
        f"messages={len(request.messages)}, max_tokens={request.max_tokens}, "
        f"project_id={request.project_id}"
    )
    if request.messages:
        first_msg = request.messages[0]
        logger.info(
            f"DEBUG[{request_hash}] First message: role={first_msg.role}, "
            f"content_len={len(first_msg.content)}, preview={first_msg.content[:100]}..."
        )

    # Check for capability-based routing first
    if request.routing_config and request.routing_config.capability:
        from app.constants import get_model_for_capability

        try:
            resolved_model = get_model_for_capability(
                request.routing_config.capability,
                provider_override=request.routing_config.provider_preference,
            )
            logger.info(
                f"DEBUG[{request_hash}] Capability routing: "
                f"{request.routing_config.capability} -> {resolved_model}"
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e
    else:
        # Resolve model alias to canonical name (reuse OpenAI compat mapping)
        from app.api.openai_compat import MODEL_MAPPING

        resolved_model = MODEL_MAPPING.get(request.model, request.model)
        if resolved_model != request.model:
            logger.info(f"DEBUG[{request_hash}] Model resolved: {request.model} -> {resolved_model}")

    # Determine provider
    provider = _get_provider(resolved_model)
    skip_cache = x_skip_cache and x_skip_cache.lower() == "true"

    # Validate max_tokens against model output limit
    max_tokens_validation = validate_max_tokens(resolved_model, request.max_tokens)
    effective_max_tokens = max_tokens_validation.effective_max_tokens
    max_tokens_warning = max_tokens_validation.warning
    was_max_tokens_capped = not max_tokens_validation.is_valid

    # Log if max_tokens was capped
    if was_max_tokens_capped:
        logger.warning(
            f"max_tokens capped for {request.model}: {request.max_tokens} -> {effective_max_tokens}"
        )

    # Get or create session if persistence is enabled
    session: DBSession | None = None
    context_messages: list[Message] = []
    session_id = request.session_id or str(uuid.uuid4())

    # Always create sessions - no opt-out (decision d1)
    is_new_session = False
    if db:
        session, context_messages, is_new_session = await _get_or_create_session(
            db,
            request.session_id,
            request.project_id,
            provider,
            resolved_model,
            purpose=request.purpose,
            session_type="completion",
            external_id=request.external_id,
        )
        session_id = session.id
        # Publish session_start event for new sessions
        if is_new_session:
            await publish_session_start(session_id, resolved_model, request.project_id)

    # Build full message list: context + new messages
    # Only add new messages that aren't already in context
    new_messages = [
        Message(role=m.role, content=m.content)  # type: ignore[arg-type]
        for m in request.messages
    ]

    # If we have context, only send the last user message as new
    # The context already contains prior conversation
    all_messages = context_messages + new_messages if context_messages else new_messages

    messages_dict = [{"role": m.role, "content": m.content} for m in all_messages]

    # Inject safety directive for autonomous agents
    if request.routing_config and request.routing_config.is_autonomous:
        from agents.registry import inject_safety_directive

        # Find or create system message
        system_idx = next(
            (i for i, m in enumerate(messages_dict) if m["role"] == "system"),
            None,
        )
        if system_idx is not None:
            # Prepend safety directive to existing system message
            original_content = messages_dict[system_idx]["content"]
            messages_dict[system_idx]["content"] = inject_safety_directive(
                original_content, is_autonomous=True
            )
            logger.info("Safety directive injected into existing system message")
        else:
            # Create new system message with safety directive
            from agents.registry import get_safety_directive

            safety_msg = {"role": "system", "content": get_safety_directive()}
            messages_dict.insert(0, safety_msg)
            logger.info("Safety directive injected as new system message")

    # Inject memory context if enabled (using progressive disclosure)
    memory_facts_injected = 0
    loaded_memory_uuids: list[str] = []
    if request.use_memory:
        memory_group = request.memory_group_id
        scope, scope_id = parse_memory_group_id(memory_group)
        try:
            messages_dict, progressive_context = await inject_progressive_context(
                messages=messages_dict,
                scope=scope,
                scope_id=scope_id,
            )
            memory_facts_injected = (
                len(progressive_context.mandates)
                + len(progressive_context.guardrails)
                + len(progressive_context.reference)
            )
            loaded_memory_uuids = progressive_context.get_loaded_uuids()
            if memory_facts_injected > 0:
                logger.info(
                    f"DEBUG[{request_hash}] Injected {memory_facts_injected} memory facts (scope={scope.value})"
                )
                # Track loaded memories asynchronously
                await track_loaded_batch(loaded_memory_uuids)
        except Exception as e:
            logger.warning(f"Memory injection failed (continuing without): {e}")

    # Check context window usage before proceeding
    # NOTE: We intentionally do NOT auto-compress here. Per Anthropic's harness
    # architecture, the caller (SummitFlow) should handle context management by:
    # 1. Monitoring context_usage in responses
    # 2. Checkpointing work (git commit, task update) when approaching limits
    # 3. Starting a fresh session with targeted file reads
    # This preserves the external scaffolding pattern that enables long-running agents.
    estimated_input_tokens = count_message_tokens(messages_dict)
    context_usage_info: ContextUsageInfo | None = None
    if db and session:
        can_proceed, ctx_usage = await check_context_before_request(
            db, session_id, resolved_model, estimated_input_tokens
        )
        if not can_proceed:
            raise HTTPException(
                status_code=413,
                detail=(
                    f"Context window limit exceeded ({ctx_usage.percent_used:.0%} used). "
                    "Start a new session or reduce conversation history."
                ),
            )
        context_usage_info = ContextUsageInfo(
            used_tokens=ctx_usage.used_tokens,
            limit_tokens=ctx_usage.limit_tokens,
            percent_used=ctx_usage.percent_used,
            remaining_tokens=ctx_usage.remaining_tokens,
            warning=ctx_usage.warning,
        )
        if should_emit_warning(ctx_usage.percent_used):
            logger.warning(f"Session {session_id}: {ctx_usage.warning}")

    # Check response cache first (unless bypassed)
    cache = get_response_cache()
    if not skip_cache:
        cached = await cache.get(
            model=resolved_model,
            messages=messages_dict,
            max_tokens=request.max_tokens,
            temperature=request.temperature,
        )
        if cached:
            logger.info(f"Returning cached response for {resolved_model}")
            # Always save to session (mandatory tracking)
            if db and session:
                await _save_messages(
                    db,
                    session_id,
                    request.messages,
                    cached.content,
                    cached.input_tokens,
                    cached.output_tokens,
                )
                # Log token usage for cached response too
                cost = estimate_cost(cached.input_tokens, cached.output_tokens, resolved_model)
                await log_token_usage(
                    db,
                    session_id,
                    resolved_model,
                    cached.input_tokens,
                    cached.output_tokens,
                    cost.total_cost_usd,
                )
                # Publish complete event for cached response (skip message events)
                await publish_complete(
                    session_id, cached.input_tokens, cached.output_tokens, cost.total_cost_usd
                )
                await db.commit()
            # Build output_usage for cached response
            cached_output_usage = build_output_usage(
                output_tokens=cached.output_tokens,
                max_tokens_requested=effective_max_tokens,
                model=resolved_model,
                finish_reason=cached.finish_reason,
                validation_warning=max_tokens_warning,
            )
            cached_output_usage_info = OutputUsageInfo(
                output_tokens=cached_output_usage.output_tokens,
                max_tokens_requested=cached_output_usage.max_tokens_requested,
                model_limit=cached_output_usage.model_limit,
                was_truncated=cached_output_usage.was_truncated,
                warning=cached_output_usage.warning,
            )
            return CompletionResponse(
                content=cached.content,
                model=cached.model,
                provider=cached.provider,
                usage=UsageInfo(
                    input_tokens=cached.input_tokens,
                    output_tokens=cached.output_tokens,
                    total_tokens=cached.input_tokens + cached.output_tokens,
                    cache=None,
                ),
                context_usage=context_usage_info,
                output_usage=cached_output_usage_info,
                session_id=session_id,
                finish_reason=cached.finish_reason,
                from_cache=True,
                memory_facts_injected=memory_facts_injected,
            )

    try:
        # Get adapter
        adapter = _get_adapter(provider)

        # Determine thinking level
        thinking_level = request.thinking_level
        if request.auto_thinking and not thinking_level and _should_enable_thinking(all_messages):
            # Auto-detect complex requests and enable thinking
            thinking_level = "medium"

        # Convert tools to API format if provided
        tools_api: list[dict[str, Any]] | None = None
        if request.tools:
            tools_api = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                    **(
                        {"allowed_callers": t.allowed_callers}
                        if t.allowed_callers != ["direct"]
                        else {}
                    ),
                }
                for t in request.tools
            ]

        # Build response_format dict for adapter
        response_format_dict: dict[str, Any] | None = None
        if request.response_format:
            response_format_dict = {
                "type": request.response_format.type,
                "schema": request.response_format.schema_,
            }

        # Make completion request with full context
        # Convert messages_dict (which includes injected memory context) back to Message objects
        messages_for_adapter = [
            Message(role=m["role"], content=m["content"]) for m in messages_dict
        ]
        result: CompletionResult = await adapter.complete(
            messages=messages_for_adapter,
            model=resolved_model,
            max_tokens=effective_max_tokens,  # Use validated/capped value
            temperature=request.temperature,
            enable_caching=request.enable_caching,
            cache_ttl=request.cache_ttl,
            thinking_level=thinking_level,
            tools=tools_api,
            enable_programmatic_tools=request.enable_programmatic_tools,
            container_id=request.container_id,
            response_format=response_format_dict,
        )

        # Validate JSON response against schema if structured output was requested
        if (
            request.response_format
            and request.response_format.type == "json_object"
            and request.response_format.schema_
        ):
            is_valid, validation_error = validate_json_response(
                result.content, request.response_format.schema_
            )
            if not is_valid:
                logger.warning(f"JSON response validation failed: {validation_error}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Model output does not match the provided JSON schema: {validation_error}",
                )

        # Check if response is an error that should NOT be cached
        # These false positives would poison the cache and cause repeated failures
        def _is_error_response(content: str) -> bool:
            """Detect error responses that should not be cached."""
            error_indicators = [
                "Usage Policy",
                "violate",
                "unable to respond to this request",
                "rate limit",
                "authentication failed",
            ]
            content_lower = content.lower()
            return any(ind.lower() in content_lower for ind in error_indicators)

        # Cache the response for future identical requests (but NOT errors)
        if not skip_cache and not _is_error_response(result.content):
            await cache.set(
                model=resolved_model,
                messages=messages_dict,
                max_tokens=request.max_tokens,
                temperature=request.temperature,
                content=result.content,
                provider=result.provider,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                finish_reason=result.finish_reason,
            )
        elif _is_error_response(result.content):
            logger.warning(
                f"Not caching error response for {request.model}: {result.content[:100]}..."
            )

        # Always save messages to database (mandatory tracking)
        if db and session:
            await _save_messages(
                db,
                session_id,
                request.messages,
                result.content,
                result.input_tokens,
                result.output_tokens,
            )
            # Publish message events for user input and assistant response
            for msg in request.messages:
                if msg.role in ("user", "system"):
                    content_str = msg.content if isinstance(msg.content, str) else str(msg.content)
                    await publish_message(session_id, msg.role, content_str)
            await publish_message(session_id, "assistant", result.content, result.output_tokens)

            # Log token usage for cost tracking
            cost = estimate_cost(result.input_tokens, result.output_tokens, resolved_model)
            await log_token_usage(
                db,
                session_id,
                resolved_model,
                result.input_tokens,
                result.output_tokens,
                cost.total_cost_usd,
            )
            # Publish complete event
            await publish_complete(
                session_id, result.input_tokens, result.output_tokens, cost.total_cost_usd
            )
            # Update provider metadata (cache info, etc.)
            if result.cache_metrics:
                await _update_provider_metadata(
                    db,
                    session,
                    {
                        "cache_creation_input_tokens": result.cache_metrics.cache_creation_input_tokens,
                        "cache_read_input_tokens": result.cache_metrics.cache_read_input_tokens,
                    },
                )
            await db.commit()

        # Build cache info if available
        cache_info = None
        if result.cache_metrics:
            cache_info = CacheInfo(
                cache_creation_input_tokens=result.cache_metrics.cache_creation_input_tokens,
                cache_read_input_tokens=result.cache_metrics.cache_read_input_tokens,
                cache_hit_rate=result.cache_metrics.cache_hit_rate,
            )

        # Build thinking info if available
        thinking_info = None
        if result.thinking_content:
            # Estimate thinking cost (thinking tokens count as input tokens)
            thinking_cost = None
            if result.thinking_tokens:
                cost_estimate = estimate_cost(result.thinking_tokens, 0, resolved_model)
                thinking_cost = cost_estimate.input_cost_usd

            thinking_info = ThinkingInfo(
                content=result.thinking_content,
                tokens=result.thinking_tokens,
                level_used=thinking_level,
                cost_usd=thinking_cost,
            )

        # Build tool calls info if available
        tool_calls_info: list[ToolCallInfo] | None = None
        if result.tool_calls:
            tool_calls_info = [
                ToolCallInfo(
                    id=tc.id,
                    name=tc.name,
                    input=tc.input,
                    caller_type=tc.caller_type,
                    caller_tool_id=tc.caller_tool_id,
                )
                for tc in result.tool_calls
            ]

        # Build container info if available
        container_info: ContainerInfo | None = None
        if result.container:
            container_info = ContainerInfo(
                id=result.container.id,
                expires_at=result.container.expires_at,
            )

        # Build output usage info with truncation detection
        output_usage = build_output_usage(
            output_tokens=result.output_tokens,
            max_tokens_requested=effective_max_tokens,
            model=resolved_model,
            finish_reason=result.finish_reason,
            validation_warning=max_tokens_warning,
        )
        output_usage_info = OutputUsageInfo(
            output_tokens=output_usage.output_tokens,
            max_tokens_requested=output_usage.max_tokens_requested,
            model_limit=output_usage.model_limit,
            was_truncated=output_usage.was_truncated,
            warning=output_usage.warning,
        )

        # Log truncation event for telemetry
        if output_usage.was_truncated and db:
            truncation_event = TruncationEvent(
                session_id=session_id if session else None,
                model=resolved_model,
                endpoint="complete",
                max_tokens_requested=effective_max_tokens,
                output_tokens=result.output_tokens,
                model_limit=output_usage.model_limit,
                was_capped=1 if was_max_tokens_capped else 0,
                project_id=request.project_id,
            )
            db.add(truncation_event)
            await db.commit()
            logger.info(
                f"Response truncated: model={resolved_model}, "
                f"tokens={result.output_tokens}/{effective_max_tokens}"
            )

        # Track cited memory rules from response
        if loaded_memory_uuids and result.content:
            try:
                # Extract citation prefixes from response
                cited_prefixes = extract_uuid_prefixes(result.content)
                if cited_prefixes:
                    # Resolve prefixes to full UUIDs
                    memory_group = request.memory_group_id
                    scope, scope_id = parse_memory_group_id(memory_group)
                    group_id = "global" if scope.value == "global" else f"{scope.value}-{scope_id}"
                    prefix_to_uuid = await resolve_full_uuids(cited_prefixes, group_id)
                    cited_uuids = list(prefix_to_uuid.values())
                    if cited_uuids:
                        await track_referenced_batch(cited_uuids)
                        logger.info(f"Tracked {len(cited_uuids)} cited memory rules")
            except Exception as e:
                logger.warning(f"Citation tracking failed (continuing): {e}")

        # Build memory UUIDs string for feedback attribution
        memory_uuids_str = ",".join(loaded_memory_uuids) if loaded_memory_uuids else None

        return CompletionResponse(
            content=result.content,
            model=result.model,
            provider=result.provider,
            usage=UsageInfo(
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                total_tokens=result.input_tokens + result.output_tokens,
                cache=cache_info,
            ),
            context_usage=context_usage_info,
            output_usage=output_usage_info,
            session_id=session_id,
            finish_reason=result.finish_reason,
            from_cache=False,
            thinking=thinking_info,
            tool_calls=tool_calls_info,
            container=container_info,
            memory_facts_injected=memory_facts_injected,
            memory_uuids=memory_uuids_str,
        )

    except ValueError as e:
        # API key not configured
        logger.error(f"Configuration error: {e}")
        if session_id:
            await publish_error(session_id, "ConfigurationError", str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Configuration error: {e}. Check environment variables (ANTHROPIC_API_KEY, GEMINI_API_KEY).",
        ) from e

    except RateLimitError as e:
        logger.warning(f"Rate limit for {e.provider}")
        if session_id:
            await publish_error(session_id, "RateLimitError", str(e))
        retry_after = str(int(e.retry_after)) if e.retry_after else "60"
        raise HTTPException(
            status_code=429,
            detail=(
                f"Rate limit exceeded for {e.provider}. "
                f"Wait {retry_after}s before retrying. Consider using prompt caching (enable_caching: true)."
            ),
            headers={"Retry-After": retry_after},
        ) from e

    except AuthenticationError as e:
        logger.error(f"Auth error for {e.provider}")
        if session_id:
            await publish_error(session_id, "AuthenticationError", str(e))
        env_var = "ANTHROPIC_API_KEY" if e.provider == "claude" else "GEMINI_API_KEY"
        raise HTTPException(
            status_code=401,
            detail=f"Authentication failed for {e.provider}. Verify {env_var} is set and valid.",
        ) from e

    except ProviderError as e:
        logger.error(f"Provider error: {e}")
        if session_id:
            await publish_error(session_id, "ProviderError", str(e))
        status_code = e.status_code or 500
        detail = str(e)
        if e.retriable:
            detail += " This error may be transient; retry may succeed."
        raise HTTPException(status_code=status_code, detail=detail) from e

    except HTTPException:
        # Let HTTPExceptions pass through (e.g., JSON validation 400 errors)
        raise

    except Exception as e:
        logger.exception(f"Unexpected error in /complete: {e}")
        if session_id:
            await publish_error(session_id, "UnexpectedError", str(e))
        raise HTTPException(
            status_code=500,
            detail="Internal server error. Check logs for details.",
        ) from e


# Estimation schemas and endpoint
class EstimateRequest(BaseModel):
    """Request body for cost estimation endpoint."""

    model: str = Field(..., description="Model identifier")
    messages: list[MessageInput] = Field(..., description="Conversation messages")
    max_tokens: int = Field(default=4096, ge=1, le=100000, description="Max tokens in response")


class EstimateResponse(BaseModel):
    """Response body for cost estimation endpoint."""

    input_tokens: int = Field(..., description="Estimated input tokens")
    estimated_output_tokens: int = Field(..., description="Estimated output tokens")
    total_tokens: int = Field(..., description="Total estimated tokens")
    estimated_cost_usd: float = Field(..., description="Estimated cost in USD")
    context_limit: int = Field(..., description="Model context limit")
    context_usage_percent: float = Field(..., description="Percentage of context used")
    context_warning: str | None = Field(default=None, description="Warning if approaching limit")


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(request: EstimateRequest) -> EstimateResponse:
    """
    Estimate tokens and cost before making a completion request.

    Returns token counts, estimated cost, and context limit warnings.
    """
    from app.api.openai_compat import MODEL_MAPPING

    resolved_model = MODEL_MAPPING.get(request.model, request.model)
    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]

    estimate_result = estimate_request(
        messages=messages_dict,
        model=resolved_model,
        max_tokens=request.max_tokens,
    )

    return EstimateResponse(
        input_tokens=estimate_result.input_tokens,
        estimated_output_tokens=estimate_result.estimated_output_tokens,
        total_tokens=estimate_result.total_tokens,
        estimated_cost_usd=estimate_result.estimated_cost_usd,
        context_limit=estimate_result.context_limit,
        context_usage_percent=estimate_result.context_usage_percent,
        context_warning=estimate_result.context_warning,
    )
