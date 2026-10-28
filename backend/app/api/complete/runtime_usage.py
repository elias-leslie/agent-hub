"""Hub accounting over per-call pi-mono messages, without changing replay usage."""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from app.constants.catalog import MODEL_CATALOG_BY_ID
from app.llm.model_resolver import upstream_model_id
from app.llm.types import AssistantMessage, Usage, UsageCost
from app.llm.utils.outcomes import is_model_switch, outcome_details, outcome_of

if TYPE_CHECKING:
    from .types import CompletionInternalResult

logger = logging.getLogger(__name__)


def aggregate_message_usage(
    final: AssistantMessage, messages: list[AssistantMessage],
) -> AssistantMessage:
    """Copy the final answer with request totals; context messages stay per call."""
    usage = Usage()
    for message in messages:
        for field in ("input", "output", "cache_read", "cache_write", "total_tokens", "reasoning"):
            setattr(usage, field, getattr(usage, field) + getattr(message.usage, field))
        for field in UsageCost.__dataclass_fields__:
            setattr(usage.cost, field, getattr(usage.cost, field) + getattr(message.usage.cost, field))
    return replace(final, usage=usage)


def _switched_to(message: AssistantMessage) -> str | None:
    """The provider-reported model when it is a different model than the one requested."""
    reported = (getattr(message, "response_model", None) or "").strip()
    return reported if reported and is_model_switch(message.model, reported) else None


def accounting_model(message: AssistantMessage, fallback: str) -> str:
    """Catalog identity of the model that answered, so pricing follows what ran.

    A reported model that differs from the requested one wins when the catalog
    knows it; otherwise route identity is kept when the upstream id matches.
    """
    switched = _switched_to(message)
    if switched:
        for key in (switched, f"{message.provider}/{switched}"):
            if key in MODEL_CATALOG_BY_ID:
                return key
    entry = MODEL_CATALOG_BY_ID.get(fallback)
    if entry and message.provider == entry.provider and message.model == upstream_model_id(fallback, entry.provider):
        return fallback
    if message.model in MODEL_CATALOG_BY_ID:
        return message.model
    qualified = f"{message.provider}/{message.model}"
    if qualified in MODEL_CATALOG_BY_ID:
        return qualified
    return message.model or fallback


def served_model(message: AssistantMessage, fallback: str) -> str:
    """Model that actually answered, for session events: the provider-reported model when it differs."""
    return (_switched_to(message) or accounting_model(message, fallback))[:100]


def outcome_usage(message: AssistantMessage | None) -> dict[str, object] | None:
    """Session-event ``usage`` payload carrying the message's typed provider outcome, if any."""
    outcome = outcome_of(message) if message is not None else None
    return {"provider_outcome": outcome_details(outcome)} if outcome else None


async def persist_failed_attempt_usage(
    db: AsyncSession,
    result: CompletionInternalResult,
    model: str,
    session_id: str | None,
    *,
    project_id: str | None = None,
    agent_slug: str | None = None,
) -> None:
    """Keep reported usage before a retry discards its failed result.

    Commit this accounting now: an exhausted fallback chain raises, so the
    normal response persistence never runs and the request may roll back.
    Exceptions without a result provide no usage to reconstruct.
    """
    from app.services.context_tracker import log_token_usage
    from app.services.token_counter import estimate_usage_cost

    session_id = session_id or result.session_id
    if not session_id or session_id.startswith("ephemeral:"):
        logger.warning("Cannot attribute failed %s attempt usage without a persisted session", model)
        return
    total_cost = 0.0
    for index, message in enumerate(result.usage_messages):
        usage = message.usage
        call_model = accounting_model(message, model)
        cost = estimate_usage_cost(
            usage.input, usage.output, call_model,
            cache_read_tokens=usage.cache_read, cache_write_tokens=usage.cache_write,
        ).total_cost_usd
        total_cost += cost
        await log_token_usage(
            db, session_id, call_model, usage.input, usage.output, cost,
            cache_read_tokens=usage.cache_read, cache_write_tokens=usage.cache_write,
            compression_stats=result.compression_stats if index == 0 else None,
        )
    await db.commit()
    if project_id and total_cost > 0:
        from app.services.project_budget import record_project_cost

        await record_project_cost(project_id, total_cost)
    if agent_slug:
        from app.services.quota import record_token_usage

        await record_token_usage(agent_slug, result.input_tokens + result.output_tokens)
