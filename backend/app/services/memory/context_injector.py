"""
Context injection service for memory-augmented completions.

Retrieves relevant context from the knowledge graph and injects it
into completion requests.
"""

import logging
from typing import Any

from .service import get_memory_service

logger = logging.getLogger(__name__)

# Context injection marker
MEMORY_CONTEXT_START = "<memory-context>"
MEMORY_CONTEXT_END = "</memory-context>"


async def inject_memory_context(
    messages: list[dict[str, Any]],
    group_id: str = "default",
    max_facts: int = 10,
    max_entities: int = 5,
) -> tuple[list[dict[str, Any]], int]:
    """
    Inject relevant memory context into messages.

    Finds the last user message, searches for relevant context,
    and prepends it to the system message (or creates one).

    Args:
        messages: List of message dicts with role and content
        group_id: Memory group ID for isolation
        max_facts: Maximum facts to include
        max_entities: Maximum entities to include

    Returns:
        Tuple of (modified messages, number of facts injected)
    """
    if not messages:
        return messages, 0

    # Find last user message to use as query
    user_query = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, str):
                user_query = content
            elif isinstance(content, list):
                # Extract text from content blocks
                text_parts = [
                    block.get("text", "")
                    for block in content
                    if isinstance(block, dict) and block.get("type") == "text"
                ]
                user_query = " ".join(text_parts)
            break

    if not user_query:
        logger.debug("No user message found for memory search")
        return messages, 0

    # Get memory service and search for context
    try:
        memory = get_memory_service(group_id)
        context = await memory.get_context_for_query(
            query=user_query,
            max_facts=max_facts,
            max_entities=max_entities,
        )
    except Exception as e:
        logger.warning("Failed to retrieve memory context: %s", e)
        return messages, 0

    # If no context found, return unchanged
    if not context.relevant_facts and not context.relevant_entities:
        logger.debug("No relevant memory context found for query")
        return messages, 0

    # Build context block
    context_parts = []
    context_parts.append(MEMORY_CONTEXT_START)
    context_parts.append("Relevant information from previous conversations:")

    if context.relevant_facts:
        context_parts.append("\nFacts:")
        for fact in context.relevant_facts:
            context_parts.append(f"- {fact}")

    if context.relevant_entities:
        context_parts.append("\nKnown entities:")
        for entity in context.relevant_entities:
            context_parts.append(f"- {entity}")

    context_parts.append(MEMORY_CONTEXT_END)
    context_block = "\n".join(context_parts)

    # Inject into system message or create one
    modified_messages = list(messages)  # Copy
    first_msg = modified_messages[0] if modified_messages else None

    if first_msg and first_msg.get("role") == "system":
        # Prepend to existing system message
        existing_content = first_msg.get("content", "")
        modified_messages[0] = {
            "role": "system",
            "content": f"{context_block}\n\n{existing_content}",
        }
    else:
        # Insert new system message at beginning
        modified_messages.insert(0, {"role": "system", "content": context_block})

    facts_count = len(context.relevant_facts)
    logger.info(
        "Injected memory context: %d facts, %d entities for query: %s...",
        facts_count,
        len(context.relevant_entities),
        user_query[:50],
    )

    return modified_messages, facts_count
