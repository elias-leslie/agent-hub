"""Agent preview helper functions."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_dto import AgentDTO
from app.services.agent_routing_utils import inject_agent_mandates
from app.services.memory.context_injector import (
    build_progressive_context,
    format_progressive_context,
)
from app.services.memory.service import MemoryScope


async def build_agent_preview(
    db: AsyncSession, agent: AgentDTO
) -> tuple[str, int, int, list[str], list[str]]:
    """Build agent preview with the same prompt composition used at runtime."""
    sections = []

    mandate = await inject_agent_mandates(agent, db, prompt_mode="full")
    if mandate.system_content:
        sections.append(mandate.system_content)

    context = await build_progressive_context(
        query="",
        scope=MemoryScope.GLOBAL,
        scope_id=None,
    )

    formatted_memory = format_progressive_context(context, include_citations=True)
    if formatted_memory:
        sections.append(formatted_memory)

    combined = "\n\n".join(sections)

    mandate_uuids = [m.uuid[:8] if m.uuid else "" for m in context.mandates]
    guardrail_uuids = [g.uuid[:8] if g.uuid else "" for g in context.guardrails]

    return (
        combined,
        len(context.mandates),
        len(context.guardrails),
        [u for u in mandate_uuids if u],
        [u for u in guardrail_uuids if u],
    )
