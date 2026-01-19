"""
Canonical Clustering service for golden standard deduplication.

Implements LLM-gated deduplication per decision d2:
- On storage, check >85% similarity with existing golden standards
- Use LLM to disambiguate: is the new content a "rephrase" or a "variation"?
- Rephrases are merged into the existing canonical
- Variations are linked via [:REFINES] relationship

This prevents duplicate golden standards from polluting the context window
while preserving meaningful variations that add nuance.
"""

import logging
from enum import Enum

from pydantic import BaseModel

from app.adapters import get_completion_adapter
from app.constants import GEMINI_FLASH

from .graphiti_client import get_graphiti

logger = logging.getLogger(__name__)

# Similarity threshold for triggering LLM disambiguation (85% per d2)
SIMILARITY_THRESHOLD = 0.85


class DisambiguationResult(str, Enum):
    """Result of LLM disambiguation."""

    REPHRASE = "rephrase"  # Same meaning, different words -> merge
    VARIATION = "variation"  # Adds nuance/new info -> link


class SimilarityCheckResult(BaseModel):
    """Result of checking similarity with existing golden standards."""

    is_similar: bool
    matched_uuid: str | None = None
    matched_content: str | None = None
    similarity_score: float = 0.0


class ClusteringResult(BaseModel):
    """Result of canonical clustering."""

    action: str  # "created", "merged", "linked"
    episode_uuid: str
    canonical_uuid: str | None = None  # For merged/linked, the canonical UUID
    message: str


async def check_similarity(
    new_content: str,
    group_id: str = "global",
) -> SimilarityCheckResult:
    """
    Check if new content is similar to existing golden standards.

    Uses Graphiti's semantic search to find similar content above
    the SIMILARITY_THRESHOLD.

    Args:
        new_content: The new content to check
        group_id: Graphiti group ID for scoping

    Returns:
        SimilarityCheckResult with match info if found
    """
    graphiti = get_graphiti()
    result = SimilarityCheckResult(is_similar=False)

    try:
        # Search for similar golden standards
        edges = await graphiti.search(
            query=f"golden standard: {new_content}",
            group_ids=[group_id],
            num_results=5,
        )

        for edge in edges:
            score = getattr(edge, "score", 0.0)
            source_desc = getattr(edge, "source_description", "") or ""

            # Only consider golden standards
            if "golden_standard" not in source_desc:
                continue

            if score >= SIMILARITY_THRESHOLD:
                result.is_similar = True
                result.matched_uuid = edge.uuid
                result.matched_content = edge.fact or ""
                result.similarity_score = score
                logger.debug(
                    "Found similar golden standard (score=%.2f): %s",
                    score,
                    edge.uuid,
                )
                break

    except Exception as e:
        logger.error("Failed to check similarity: %s", e)

    return result


async def disambiguate_with_llm(
    new_content: str,
    existing_content: str,
) -> DisambiguationResult:
    """
    Use LLM to determine if new content is a rephrase or variation.

    Rephrase: Same meaning, different words (merge)
    Variation: Adds nuance, clarification, or new information (link)

    Args:
        new_content: The new content being added
        existing_content: The existing golden standard content

    Returns:
        DisambiguationResult indicating how to handle
    """
    adapter = get_completion_adapter("gemini")

    prompt = f"""You are a semantic analyzer for a knowledge base. Compare these two rules/standards and determine their relationship.

EXISTING RULE:
{existing_content}

NEW RULE:
{new_content}

Analyze:
1. Do they convey the SAME core meaning/instruction?
2. Does the new rule add significant NEW information not in the existing rule?

Respond with EXACTLY one word:
- "rephrase" if the new rule says the same thing in different words (should be merged)
- "variation" if the new rule adds meaningful new information or nuance (should be linked)

Your response (one word only):"""

    try:
        response = await adapter.complete(
            messages=[{"role": "user", "content": prompt}],
            model=GEMINI_FLASH,
            max_tokens=10,
        )

        result_text = response.content.strip().lower()

        if "rephrase" in result_text:
            logger.info("LLM classified as REPHRASE")
            return DisambiguationResult.REPHRASE
        elif "variation" in result_text:
            logger.info("LLM classified as VARIATION")
            return DisambiguationResult.VARIATION
        else:
            # Default to variation (safer - preserves info)
            logger.warning("LLM returned unexpected: %s, defaulting to variation", result_text)
            return DisambiguationResult.VARIATION

    except Exception as e:
        logger.error("LLM disambiguation failed: %s, defaulting to variation", e)
        return DisambiguationResult.VARIATION


async def merge_into_golden(
    golden_uuid: str,
    new_content: str,
) -> bool:
    """
    Merge new content into existing golden standard.

    Updates the canonical entry's synonyms list and increments ref_count.

    Args:
        golden_uuid: UUID of the existing golden standard
        new_content: The new content being merged

    Returns:
        True if successful
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    # Update the golden standard with synonym and ref_count
    query = """
    MATCH (e:Episodic {uuid: $uuid})
    SET e.synonyms = CASE
            WHEN e.synonyms IS NULL THEN [$new_content]
            WHEN NOT $new_content IN e.synonyms THEN e.synonyms + $new_content
            ELSE e.synonyms
        END,
        e.ref_count = COALESCE(e.ref_count, 1) + 1,
        e.updated_at = datetime()
    RETURN e.uuid AS uuid, size(e.synonyms) AS synonym_count
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            uuid=golden_uuid,
            new_content=new_content[:500],  # Truncate to avoid huge synonyms
        )

        if records:
            synonym_count = records[0]["synonym_count"]
            logger.info(
                "Merged content into golden %s (synonyms=%d)",
                golden_uuid,
                synonym_count,
            )
            return True
        else:
            logger.warning("Golden standard %s not found for merge", golden_uuid)
            return False

    except Exception as e:
        logger.error("Failed to merge into golden standard: %s", e)
        return False


async def link_as_refinement(
    golden_uuid: str,
    new_uuid: str,
) -> bool:
    """
    Link new episode as a refinement of existing golden standard.

    Creates a [:REFINES] relationship from the new episode to the canonical.

    Args:
        golden_uuid: UUID of the existing golden standard
        new_uuid: UUID of the new episode

    Returns:
        True if successful
    """
    graphiti = get_graphiti()
    driver = graphiti.driver

    # Create REFINES relationship
    query = """
    MATCH (canonical:Episodic {uuid: $golden_uuid})
    MATCH (variation:Episodic {uuid: $new_uuid})
    MERGE (variation)-[r:REFINES]->(canonical)
    SET r.created_at = datetime()
    RETURN canonical.uuid AS canonical, variation.uuid AS variation
    """

    try:
        records, _, _ = await driver.execute_query(
            query,
            golden_uuid=golden_uuid,
            new_uuid=new_uuid,
        )

        if records:
            logger.info(
                "Linked %s as refinement of canonical %s",
                new_uuid,
                golden_uuid,
            )
            return True
        else:
            logger.warning(
                "Failed to link: one or both nodes not found (%s, %s)",
                golden_uuid,
                new_uuid,
            )
            return False

    except Exception as e:
        logger.error("Failed to create REFINES relationship: %s", e)
        return False


async def handle_new_golden_standard(
    new_content: str,
    group_id: str = "global",
) -> tuple[str, str | None]:
    """
    Handle a new golden standard with deduplication.

    Checks for similar existing golden standards and either:
    - Returns "create" if no similar content exists
    - Returns "merge" with canonical UUID if it's a rephrase
    - Returns "link" with canonical UUID if it's a variation

    Args:
        new_content: The new golden standard content
        group_id: Graphiti group ID for scoping

    Returns:
        Tuple of (action, canonical_uuid or None)
        action: "create", "merge", or "link"
    """
    # Check for similar existing content
    similarity = await check_similarity(new_content, group_id)

    if not similarity.is_similar or not similarity.matched_uuid:
        return ("create", None)

    # LLM disambiguation
    disambiguation = await disambiguate_with_llm(
        new_content,
        similarity.matched_content or "",
    )

    if disambiguation == DisambiguationResult.REPHRASE:
        # Merge into existing
        await merge_into_golden(similarity.matched_uuid, new_content)
        return ("merge", similarity.matched_uuid)
    else:
        # Will need to link after creation
        return ("link", similarity.matched_uuid)
