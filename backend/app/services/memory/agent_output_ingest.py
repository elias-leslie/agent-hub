"""Atomic memory candidate extraction from long agent outputs."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from app.adapters.base import AuthenticationError, ProviderError, RateLimitError

from .enrichment import enrich_memory_content
from .episode_creator_models import BatchEpisodeRequest
from .ingestion_config import LEARNING
from .memory_models import MemoryScope, MemorySource

logger = logging.getLogger(__name__)

DEFAULT_EXTRACTOR_AGENT = "memory-curator"

_CANDIDATE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "candidates": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "content": {"type": "string"},
                    "summary": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["decision", "preference", "project_fact", "research", "task", "source_claim"],
                    },
                    "confidence": {"type": "number"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["content", "summary", "kind", "confidence", "tags"],
            },
        }
    },
    "required": ["candidates"],
}


@dataclass
class AgentOutputMemoryCandidate:
    """One atomic memory candidate derived from an agent output."""

    content: str
    summary: str
    kind: str
    confidence: float
    tags: list[str] = field(default_factory=list)


def build_agent_output_extraction_prompt(output: str) -> str:
    """Build bounded extraction prompt for long agent outputs."""
    clipped = output[-16000:] if len(output) > 16000 else output
    return (
        "Extract durable memory candidates from this agent output. "
        "Only keep facts, decisions, preferences, research conclusions, source-backed claims, "
        "or follow-up tasks that should survive beyond this chat. "
        "Skip prose, status narration, temporary implementation detail, and duplicates. "
        "Make each candidate atomic and compact.\n\n"
        f"AGENT OUTPUT:\n{clipped}\n\n"
        "Return JSON only matching the schema."
    )


def parse_agent_output_candidates(content: str | None) -> list[AgentOutputMemoryCandidate]:
    """Parse candidate JSON from memory-curator."""
    if not content:
        return []
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict) or not isinstance(parsed.get("candidates"), list):
        return []
    candidates: list[AgentOutputMemoryCandidate] = []
    for item in parsed["candidates"]:
        if not isinstance(item, dict):
            continue
        candidate_content = str(item.get("content") or "").strip()
        summary = str(item.get("summary") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if not candidate_content or not summary or kind not in {
            "decision",
            "preference",
            "project_fact",
            "research",
            "task",
            "source_claim",
        }:
            continue
        candidates.append(
            AgentOutputMemoryCandidate(
                content=candidate_content[:1000],
                summary=summary[:120],
                kind=kind,
                confidence=float(item.get("confidence") or 0.0),
                tags=[
                    tag.strip()
                    for tag in item.get("tags", [])
                    if isinstance(tag, str) and tag.strip()
                ][:10],
            )
        )
    return candidates


async def extract_agent_output_candidates(
    output: str,
    *,
    extractor_agent_slug: str = DEFAULT_EXTRACTOR_AGENT,
) -> list[AgentOutputMemoryCandidate]:
    """Use the dedicated memory-curator agent to extract atomic candidates."""
    from app.api.complete.core import complete_internal
    from app.db import async_session
    from app.services.agent_routing import get_provider_for_model
    from app.services.agent_routing_utils import inject_agent_mandates, resolve_agent

    prompt = build_agent_output_extraction_prompt(output)
    async with async_session() as db:
        resolved = await resolve_agent(extractor_agent_slug, db)
        mandate = await inject_agent_mandates(
            resolved.agent,
            db,
            prompt_mode="minimal",
            project_id="agent-hub",
            task_type="memory",
        )
        messages: list[dict[str, Any]] = []
        if mandate.system_content:
            messages.append({"role": "system", "content": mandate.system_content})
        messages.append({"role": "user", "content": prompt})
        candidate_models = [resolved.model, *list(resolved.agent.fallback_models or [])]
        last_error: Exception | None = None
        for model in dict.fromkeys(candidate_models):
            provider = resolved.provider if model == resolved.model else get_provider_for_model(model)
            try:
                result = await complete_internal(
                    messages=messages,
                    model=model,
                    provider=provider,
                    temperature=resolved.agent.temperature,
                    project_id="agent-hub",
                    db=db,
                    agent_slug=extractor_agent_slug,
                    request_source="agent_output_memory_extraction",
                    use_memory=False,
                    enable_caching=False,
                    skip_cache=True,
                    max_turns=1,
                    execute_tools=False,
                    thinking_level=resolved.agent.thinking_level,
                    response_format={"type": "json_object", "schema": _CANDIDATE_SCHEMA},
                    task_type="memory",
                    phase="agent_output_ingest",
                )
                return parse_agent_output_candidates(result.content)
            except Exception as exc:
                last_error = exc
                if isinstance(exc, AuthenticationError):
                    raise
                if not isinstance(exc, RateLimitError) and not (
                    isinstance(exc, ProviderError) and exc.retriable
                ):
                    raise
                logger.warning("Agent-output extractor model %s failed; trying fallback: %s", model, exc)
        if last_error is not None:
            raise last_error
    return []


def candidates_to_batch_requests(
    candidates: list[AgentOutputMemoryCandidate],
    *,
    source_agent_slug: str | None = None,
    session_id: str | None = None,
) -> list[BatchEpisodeRequest]:
    """Convert extraction candidates into episode-creator batch requests."""
    requests: list[BatchEpisodeRequest] = []
    now = datetime.now(UTC)
    for index, candidate in enumerate(candidates):
        enrichment = enrich_memory_content(
            candidate.content,
            source="agent_output",
            observation_type=candidate.kind,
            summary=candidate.summary,
        )
        metadata = dict(enrichment.metadata)
        metadata["agent_output_ingest"] = {
            "kind": candidate.kind,
            "confidence": candidate.confidence,
            "source_agent_slug": source_agent_slug,
            "session_id": session_id,
        }
        requests.append(
            BatchEpisodeRequest(
                content=candidate.content,
                name=f"agent_output_{candidate.kind}_{now.strftime('%Y%m%d_%H%M%S')}_{index}",
                config=LEARNING,
                source_description=(
                    f"agent_output kind:{candidate.kind} confidence:{candidate.confidence:.2f}"
                ),
                reference_time=now,
                source=MemorySource.SYSTEM,
                summary=candidate.summary,
                tags=candidate.tags,
                metadata=metadata,
            )
        )
    return requests


async def ingest_agent_output_candidates(
    output: str,
    *,
    scope: MemoryScope = MemoryScope.GLOBAL,
    scope_id: str | None = None,
    source_agent_slug: str | None = None,
    session_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Extract agent-output memory candidates, optionally storing them."""
    from .episode_creator import get_episode_creator

    candidates = await extract_agent_output_candidates(output)
    requests = candidates_to_batch_requests(
        candidates,
        source_agent_slug=source_agent_slug,
        session_id=session_id,
    )
    if dry_run:
        return {
            "stored": False,
            "candidate_count": len(candidates),
            "candidates": [candidate.__dict__ for candidate in candidates],
        }
    result = await get_episode_creator(scope=scope, scope_id=scope_id).batch_create(requests)
    return {
        "stored": True,
        "candidate_count": len(candidates),
        "successful": result.successful,
        "deduplicated": result.deduplicated,
        "failed": result.failed,
    }
