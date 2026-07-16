"""
Unified completion service for chat, voice, and streaming.
"""

import asyncio
import logging
import uuid
from typing import Any, ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.complete.core import complete_internal
from app.services.agent_routing import get_provider_for_model as get_provider
from app.services.completion.helpers import (
    get_thinking_level,
    handle_episode_storage,
    inject_memory_context,
)
from app.services.completion.types import (
    CompletionOptions,
    CompletionServiceResult,
    CompletionSource,
)

logger = logging.getLogger(__name__)


async def _log_completion_cost(
    project_id: str,
    provider: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
    source: str = "completion",
    session_id: str | None = None,
) -> None:
    """Create a lightweight session and log costs for a CompletionService call.

    Fire-and-forget: logs warning on failure, never raises.
    """
    try:
        from app.db import async_session
        from app.models import CostLog
        from app.models import Session as DBSession
        from app.services.project_budget import record_project_cost
        from app.services.token_counter import estimate_cost

        session_id = session_id or str(uuid.uuid4())
        cost = estimate_cost(input_tokens, output_tokens, model)

        async with async_session() as db:
            session = DBSession(
                id=session_id,
                project_id=project_id,
                provider=provider,
                model=model,
                status="completed",
                session_type="completion",
                request_source=source,
                models_used=[model],
                providers_used=[provider],
            )
            db.add(session)

            cost_log = CostLog(
                session_id=session_id,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost_usd=cost.total_cost_usd,
            )
            db.add(cost_log)
            await record_project_cost(project_id, cost.total_cost_usd)
            await db.commit()

    except Exception:
        logger.warning(
            "Failed to log completion cost for project %s", project_id, exc_info=True
        )


class CompletionService:
    """Unified completion service for all request sources."""

    _background_tasks: ClassVar[set[asyncio.Task[None]]] = set()

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    async def complete(self, options: CompletionOptions) -> CompletionServiceResult:
        """Execute a completion request."""
        provider = get_provider(options.model)
        session_id = options.session_id or str(uuid.uuid4())
        messages, memory_facts = await inject_memory_context(
            options,
            list(options.messages),
            db=self.db,
        )

        result = await complete_internal(
            messages=messages,
            model=options.model,
            provider=provider,
            temperature=options.temperature,
            project_id=options.project_id,
            db=None,
            session_id=session_id,
            enable_caching=options.enable_caching,
            cache_ttl=options.cache_ttl,
            thinking_level=get_thinking_level(options, messages),
            tools=options.tools,
            enable_programmatic_tools=options.enable_programmatic_tools,
            container_id=options.container_id,
            response_format=options.response_format,
            canonical_context_preinjected=True,
        )

        episode_uuid = await handle_episode_storage(
            options, messages, result.content, self._background_tasks
        )

        # Log cost if tokens were consumed
        if result.input_tokens + result.output_tokens > 0:
            await _log_completion_cost(
                project_id=options.project_id,
                provider=result.provider,
                model=result.model,
                input_tokens=result.input_tokens,
                output_tokens=result.output_tokens,
                source=options.source.value,
                session_id=session_id,
            )

        return CompletionServiceResult(
            content=result.content,
            model=result.model,
            provider=result.provider,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            session_id=session_id,
            finish_reason=result.finish_reason,
            thinking_content=result.thinking_content,
            thinking_tokens=result.thinking_tokens,
            tool_calls=result.tool_calls,
            container=result.container,
            cache_metrics=result.cache_metrics,
            memory_facts_injected=memory_facts,
            episode_uuid=episode_uuid,
        )


async def complete_with_memory(
    messages: list[dict[str, Any]],
    model: str,
    project_id: str,
    source: CompletionSource = CompletionSource.CHAT,
    use_memory: bool = True,
    store_as_episode: bool = True,
    memory_group_id: str | None = None,
    max_tokens: int | None = None,
    temperature: float = 1.0,
    db: AsyncSession | None = None,
) -> CompletionServiceResult:
    """Convenience function for completions with memory."""
    options = CompletionOptions(
        model=model,
        messages=messages,
        project_id=project_id,
        source=source,
        use_memory=use_memory,
        store_as_episode=store_as_episode,
        memory_group_id=memory_group_id,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    return await CompletionService(db=db).complete(options)
