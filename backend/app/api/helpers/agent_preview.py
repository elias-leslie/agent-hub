"""Agent preview helper functions."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.agent_dto import AgentDTO
from app.services.memory.context_injector import (
    build_progressive_context,
    format_progressive_context,
)
from app.services.memory.service import MemoryScope


async def build_agent_preview(
    db: AsyncSession, agent: AgentDTO
) -> tuple[str, int, int, list[str], list[str]]:
    """Build agent preview with combined prompt and memory context.

    Args:
        db: Database session
        agent: Agent DTO

    Returns:
        Tuple of (combined_prompt, mandate_count, guardrail_count, mandate_uuids, guardrail_uuids)
    """
    sections = []

    # Get global instructions
    result = await db.execute(
        text("SELECT content, enabled FROM global_instructions WHERE scope = 'global'")
    )
    row = result.fetchone()
    if row and row.enabled and row.content:
        sections.append(f"<platform_context>\n{row.content}\n</platform_context>")

    sections.append(f"<agent_persona>\n{agent.system_prompt}\n</agent_persona>")

    # Build memory context
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
