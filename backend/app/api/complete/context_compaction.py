"""Context compaction — prune long conversations before hitting token limits.

Two layers. ``maybe_compact_context`` (below) trims a resumed chat's text history before the request runs. The tool
loop's own compaction (``app.llm.compaction``) shortens the history in the middle of a run, tool calls included;
``build_loop_compactor`` plugs this module's summarizer agent into it.

Operates purely in-memory on the messages_dict list. Session events
(the immutable log) are never modified. Compaction summarizes older
messages using the configured ``context-compactor`` agent and
reassembles the context with system/memory messages preserved and
recent turns protected.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from app.config import settings

if TYPE_CHECKING:
    from app.llm.compaction import Compactor, SummaryRequest, SummaryResult
    from app.llm.types import Model

logger = logging.getLogger(__name__)

# Defaults (can be overridden per-agent via strategies JSON)
_DEFAULT_THRESHOLD_PCT = 0.75
_DEFAULT_KEEP_RECENT = 6
_COMPACTOR_AGENT_SLUG = "context-compactor"


async def maybe_compact_context(
    messages_dict: list[dict[str, Any]],
    model: str,
    keep_recent: int = _DEFAULT_KEEP_RECENT,
    threshold_pct: float = _DEFAULT_THRESHOLD_PCT,
    *,
    session_id: str | None = None,
    db: Any = None,
) -> tuple[list[dict[str, Any]], bool]:
    """Compact context if token usage exceeds threshold.

    Args:
        messages_dict: Current message list (dicts with role/content).
        model: Model ID (used to look up context window).
        keep_recent: Number of recent user+assistant message pairs to protect.
        threshold_pct: Fraction of context window that triggers compaction.

    Returns:
        Tuple of (possibly compacted messages, whether compaction occurred).
    """
    from app.services.token_counter import count_message_tokens, get_context_limit

    if len(messages_dict) <= keep_recent * 2 + 2:
        # Not enough messages to compact
        return messages_dict, False

    total_tokens = count_message_tokens(messages_dict)
    context_limit = get_context_limit(model)
    usage_pct = total_tokens / context_limit if context_limit > 0 else 0

    if usage_pct < threshold_pct:
        return messages_dict, False

    # Split messages into segments
    system_messages: list[dict[str, Any]] = []
    compactable: list[dict[str, Any]] = []
    protected: list[dict[str, Any]] = []

    # Extract system messages (always first)
    idx = 0
    while idx < len(messages_dict) and messages_dict[idx].get("role") == "system":
        system_messages.append(messages_dict[idx])
        idx += 1

    remaining = messages_dict[idx:]

    # Protect the last `keep_recent * 2` messages (user+assistant pairs)
    protect_count = min(keep_recent * 2, len(remaining))
    if protect_count > 0:
        compactable = remaining[:-protect_count]
        protected = remaining[-protect_count:]
    else:
        compactable = remaining
        protected = []

    if not compactable:
        return messages_dict, False

    # Summarize compactable messages using the configured compaction agent.
    summary = await _summarize_messages(compactable, session_id=session_id, db=db)
    if not summary:
        return messages_dict, False

    # Reassemble
    summary_message = {
        "role": "system",
        "content": f"[Context Summary — earlier conversation compacted]\n\n{summary}",
    }

    compacted = [*system_messages, summary_message, *protected]

    new_tokens = count_message_tokens(compacted)
    saved = total_tokens - new_tokens
    logger.info(
        "Context compacted: %d→%d tokens (saved %d, %.0f%%→%.0f%% of %d limit)",
        total_tokens, new_tokens, saved,
        usage_pct * 100, (new_tokens / context_limit * 100) if context_limit else 0,
        context_limit,
    )

    return compacted, True


async def _summarize_messages(
    messages: list[dict[str, Any]],
    *,
    session_id: str | None = None,
    db: Any = None,
) -> str | None:
    """Summarize a list of messages using the configured compaction agent.

    Uses the caller's managed database session so canonical operator context is
    verified before the compactor provider is invoked. Tokens are logged to
    CostLog against the parent session for cost visibility.
    """
    if db is None:
        logger.warning("Context compaction skipped: database session unavailable")
        return None

    from app.api.complete.core import complete_internal
    from app.services.agent_model_router import RoutingContext
    from app.services.agent_routing_utils import resolve_agent

    conversation_text = "\n".join(
        f"{m.get('role', 'unknown').upper()}: {m.get('content', '')}"
        for m in messages
    )

    try:
        try:
            resolved = await resolve_agent(
                _COMPACTOR_AGENT_SLUG,
                db,
                RoutingContext(),
            )
        except Exception:
            logger.warning("Context compactor agent not found")
            return None
        agent = resolved.agent

        system_content = (agent.system_prompt or "").strip()
        if not system_content:
            logger.warning("Context compactor agent has no system prompt")
            return None

        request_messages = [
            {"role": "system", "content": system_content},
            {"role": "user", "content": conversation_text},
        ]

        result = await complete_internal(
            messages=request_messages,
            model=resolved.model,
            provider=resolved.provider,
            temperature=agent.temperature,
            project_id="agent-hub",
            db=db,
            agent_slug=_COMPACTOR_AGENT_SLUG,
            request_source="context_compaction",
            use_memory=False,
            thinking_level=agent.thinking_level,
        )

        # Log compaction tokens to the parent session's CostLog
        if session_id and db and result.content:
            try:
                from app.services.context_tracker import log_token_usage
                from app.services.token_counter import estimate_cost

                billed_model = result.model or resolved.model
                cost = estimate_cost(result.input_tokens, result.output_tokens, billed_model)
                await log_token_usage(
                    db, session_id, billed_model,
                    result.input_tokens, result.output_tokens, cost.total_cost_usd,
                )
                logger.info(
                    "Context compaction cost: %d in + %d out tokens ($%.4f)",
                    result.input_tokens, result.output_tokens, cost.total_cost_usd,
                )
            except Exception:
                logger.warning("Failed to log context compaction tokens", exc_info=True)

        return result.content if result.content else None
    except Exception:
        logger.exception("Context compaction summarization failed")
        return None


def _summary_prompt(request: SummaryRequest) -> str:
    previous = f"<previous-summary>\n{request.previous_summary}\n</previous-summary>\n\n" if request.previous_summary else ""
    return f"{previous}<conversation>\n{request.transcript}\n</conversation>\n\n{request.prompt}"


async def summarize_with_agent(
    request: SummaryRequest, *, project_id: str | None = None, signal: asyncio.Event | None = None
) -> SummaryResult:
    """Write the loop's summary with ``settings.llm_compaction_agent_slug``, trying its primary model, then fallbacks.

    The model chain is the agent's (catalog and seed data) unless ``llm_compaction_summarizer_models`` names one, never
    a literal here. Raises when no model in the chain answers.
    """
    from app.api.complete.core import complete_internal
    from app.api.complete.runtime_usage import accounting_model, served_model
    from app.db import async_session
    from app.llm.compaction import SummaryResult
    from app.routing.registry import get_provider_for_model
    from app.services.agent_model_router import RoutingContext
    from app.services.agent_routing_completion import (
        route_preflight_error,
        thinking_level_for_provider,
    )
    from app.services.agent_routing_utils import resolve_agent
    from app.services.token_counter import estimate_usage_cost

    slug = settings.llm_compaction_agent_slug
    async with async_session() as db:
        agent = (await resolve_agent(slug, db, RoutingContext())).agent
    messages: list[dict[str, Any]] = [{"role": "user", "content": _summary_prompt(request)}]
    if (agent.system_prompt or "").strip():
        messages.insert(0, {"role": "system", "content": agent.system_prompt.strip()})
    failures: list[str] = []
    chain = settings.llm_compaction_summarizer_models or [agent.primary_model_id, *(agent.fallback_models or [])]
    for model in dict.fromkeys(chain):
        provider = get_provider_for_model(model)
        if (unavailable := await route_preflight_error(model)) is not None:
            failures.append(f"{model}: {unavailable}")
            continue
        try:
            result = await complete_internal(
                messages=messages,
                model=model,
                provider=provider,
                temperature=agent.temperature,
                project_id=project_id or "agent-hub",
                db=None,
                agent_slug=slug,
                request_source="context_compaction",
                use_memory=False,
                thinking_level=thinking_level_for_provider(provider, agent.thinking_level),
                signal=signal,
            )
        except Exception as exc:
            failures.append(f"{model}: {exc}")
            continue
        message = result.message
        if message.stop_reason in ("error", "aborted"):
            failures.append(f"{model}: {message.error_message or message.stop_reason}")
            continue
        usage = message.usage
        accounted = accounting_model(message, model)
        cost = estimate_usage_cost(
            usage.input, usage.output, accounted,
            cache_read_tokens=usage.cache_read, cache_write_tokens=usage.cache_write,
        )
        return SummaryResult(
            text=result.content or "",
            model=served_model(message, model),
            input_tokens=usage.input,
            output_tokens=usage.output,
            cache_read_tokens=usage.cache_read,
            cache_write_tokens=usage.cache_write,
            cost_usd=cost.total_cost_usd,
        )
    raise RuntimeError(f"no model of agent {slug!r} produced a summary: " + "; ".join(failures))


def build_loop_compactor(
    model: Model[Any], *, project_id: str | None = None, signal: asyncio.Event | None = None
) -> Compactor | None:
    """The tool loop's compactor for ``model``: its window (the catalog's, or an override) and the configured policy.

    None when compaction is off or the model has no known window.
    """
    from app.llm.compaction import CompactionPolicy, Compactor

    if not settings.llm_compaction_enabled:
        return None
    window = settings.llm_compaction_window_overrides.get(model.id) or model.context_window
    if window <= 0:
        return None
    policy = CompactionPolicy(
        context_window=window,
        reserve_tokens=settings.llm_compaction_reserve_tokens,
        keep_recent_tokens=settings.llm_compaction_keep_recent_tokens,
        tool_result_chars=settings.llm_compaction_tool_result_chars,
        read_tools=frozenset(settings.llm_compaction_read_tools),
        write_tools=frozenset(settings.llm_compaction_write_tools),
    )

    async def summarize(request: SummaryRequest) -> SummaryResult:
        return await summarize_with_agent(request, project_id=project_id, signal=signal)

    return Compactor(policy, summarize)
