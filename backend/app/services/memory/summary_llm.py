"""LLM-based summary generation for session summaries.

Routes through Agent Hub's completion pipeline (complete_internal) so that
summarizer sessions are tracked, tokens are accounted, and activity appears
on the sessions page under the ``summarizer`` agent.

The ``session-analysis`` prompt slug produces summary + memory ratings in
a single LLM call, replacing the previous two-call approach (separate
``summary-generation`` and hardcoded rater prompt).
"""

from __future__ import annotations

import logging

from app.services.memory._summary_models import LLMAnalysisResult
from app.services.memory._summary_parse import (
    create_fallback_summary,
    parse_summary_response,
)

logger = logging.getLogger(__name__)

__all__ = [
    "LLMAnalysisResult",
    "create_fallback_summary",
    "generate_via_llm",
    "parse_summary_response",
]


async def _call_llm(prompt: str, project_id: str) -> str | None:
    """Run the LLM completion and return the stripped text, or None on failure."""
    from app.api.complete.core import complete_internal
    from app.db import _get_session_factory
    from app.services.agent_model_router import RoutingContext
    from app.services.agent_routing_utils import resolve_agent

    session_factory = _get_session_factory()
    async with session_factory() as db:
        try:
            resolved = await resolve_agent(
                "summarizer",
                db,
                RoutingContext(),
            )
        except Exception:
            logger.warning("Summarizer agent not found, using fallback")
            return None

        agent = resolved.agent
        result = await complete_internal(
            messages=[{"role": "user", "content": prompt}],
            model=resolved.model,
            provider=resolved.provider,
            temperature=agent.temperature,
            project_id=project_id,
            db=db,
            agent_slug=agent.slug,
            use_memory=False,
            enable_caching=False,
            skip_cache=True,
        )
    return result.content.strip() or None


async def generate_via_llm(
    session_id: str,
    project_id: str,
    agent_slug: str | None,
    transcript: str,
    *,
    git_context: str | None = None,
    memory_contents: dict[str, str] | None = None,
) -> LLMAnalysisResult:
    """Generate summary + memory ratings using Gemini in a single call.

    Args:
        session_id: Session UUID for context.
        project_id: Project ID for context.
        agent_slug: Agent slug for context.
        transcript: Condensed session transcript.
        git_context: Raw ``git log --oneline`` output captured by Stop.sh.
        memory_contents: Dict of ``{full_uuid: content}`` for loaded memories.

    Returns:
        LLMAnalysisResult with all parsed fields.
    """
    from app.services.memory._summary_prompt import build_prompt

    prompt = await build_prompt(
        session_id,
        project_id,
        agent_slug,
        transcript,
        git_context=git_context,
        memory_contents=memory_contents,
    )
    try:
        text = await _call_llm(prompt, project_id)
        if text is None:
            logger.warning("LLM returned empty response for session %s", session_id)
            return create_fallback_summary(transcript, git_context=git_context)
        return parse_summary_response(text, memory_contents=memory_contents)
    except Exception as e:
        logger.warning("LLM summary generation failed: %s", e)
        return create_fallback_summary(transcript, git_context=git_context)
