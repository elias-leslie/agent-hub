"""
Learning extraction service for session transcripts.

Extracts learnings from Claude Code sessions and stores them in Graphiti
with confidence scoring and provisional/canonical status.

Confidence thresholds (per decision d2):
- 70+: provisional (will be surfaced, needs reinforcement)
- 90+: canonical (high confidence, immediately trusted)
"""

import json
import logging
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field

from app.adapters.gemini import GeminiAdapter
from app.constants import FAST_GEMINI_MODEL

from .service import (
    MemoryScope,
    MemorySource,
    get_memory_service,
)

# Import will be done at function level to avoid circular import

logger = logging.getLogger(__name__)

# Confidence thresholds per decision d2
PROVISIONAL_THRESHOLD = 70
CANONICAL_THRESHOLD = 90


class LearningType(str, Enum):
    """Type of learning extracted from a session."""

    VERIFIED = "verified"  # Explicitly confirmed by user (0.95 confidence)
    INFERENCE = "inference"  # Derived from successful task completion (0.80)
    PATTERN = "pattern"  # Observed pattern across interactions (0.60)


class LearningStatus(str, Enum):
    """Status of a learning in the memory system."""

    PROVISIONAL = "provisional"  # 70-89 confidence, needs reinforcement
    CANONICAL = "canonical"  # 90+ confidence, trusted


class ExtractedLearning(BaseModel):
    """A learning extracted from a session transcript."""

    content: str = Field(..., description="The learning content")
    learning_type: LearningType = Field(..., description="How the learning was derived")
    confidence: float = Field(..., ge=0, le=100, description="Confidence score 0-100")
    source_quote: str | None = Field(None, description="Quote from transcript supporting this")
    category: str = Field("domain_knowledge", description="Memory category")


class ExtractionResult(BaseModel):
    """Result of learning extraction from a session."""

    session_id: str
    learnings: list[ExtractedLearning] = []
    stored_count: int = 0
    provisional_count: int = 0
    canonical_count: int = 0
    skipped_count: int = 0
    processing_time_ms: int = 0


class ExtractLearningsRequest(BaseModel):
    """Request to extract learnings from a session transcript."""

    session_id: str = Field(..., description="ID of the session")
    transcript: str = Field(..., description="Session transcript to analyze")
    task_id: str | None = Field(None, description="Related task ID if any")
    project_id: str | None = Field(None, description="Project ID for scoping")


EXTRACTION_PROMPT = """Analyze this Claude Code session transcript and extract learnings.

For each learning, determine:
1. **Type**:
   - VERIFIED (user explicitly confirmed something, 95% confidence)
   - INFERENCE (derived from successful task completion, 80% confidence)
   - PATTERN (observed behavior or practice, 60% confidence)

2. **Category**:
   - coding_standard (best practices, style guides)
   - troubleshooting_guide (gotchas, pitfalls, fixes)
   - system_design (architecture decisions)
   - operational_context (environment, deployment)
   - domain_knowledge (business logic, concepts)

3. **Confidence**: Base confidence for the type, adjust +/- 10% based on evidence strength

Output as JSON array:
```json
[
  {
    "content": "Clear, actionable statement of the learning",
    "learning_type": "verified|inference|pattern",
    "confidence": 60-100,
    "source_quote": "Brief quote from transcript supporting this",
    "category": "coding_standard|troubleshooting_guide|system_design|operational_context|domain_knowledge"
  }
]
```

Rules:
- Extract ONLY actionable learnings (not observations about the conversation itself)
- Focus on technical knowledge that would help in future sessions
- Skip trivial learnings (obvious statements, single-use fixes)
- Maximum 10 learnings per session
- Each learning should be self-contained and understandable without context

SESSION TRANSCRIPT:
{transcript}
"""


async def extract_learnings(request: ExtractLearningsRequest) -> ExtractionResult:
    """
    Extract learnings from a session transcript using LLM analysis.

    Uses Gemini Flash for fast, cheap extraction. Stores learnings in Graphiti
    with appropriate status based on confidence thresholds.

    Args:
        request: Session transcript and metadata

    Returns:
        ExtractionResult with counts and stored learning details
    """
    start_time = datetime.now()

    result = ExtractionResult(session_id=request.session_id)

    # Truncate very long transcripts (preserve last 10K chars - most recent context)
    transcript = request.transcript
    if len(transcript) > 15000:
        transcript = "...[truncated]...\n" + transcript[-12000:]
        logger.info(
            "Truncated transcript from %d to %d chars for session %s",
            len(request.transcript),
            len(transcript),
            request.session_id,
        )

    # Extract learnings using LLM
    prompt = EXTRACTION_PROMPT.format(transcript=transcript)

    try:
        adapter = GeminiAdapter()
        response = await adapter.complete(
            messages=[{"role": "user", "content": prompt}],
            model=FAST_GEMINI_MODEL,
            max_tokens=4096,
        )

        # Parse JSON from response
        response_text = response.get("content", "")
        learnings = _parse_learnings_json(response_text)
        result.learnings = learnings

    except Exception as e:
        logger.error("Learning extraction failed for session %s: %s", request.session_id, e)
        result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        return result

    # Store learnings in Graphiti
    # Use global scope per decision d4 (shared knowledge across all agents)
    service = get_memory_service(scope=MemoryScope.GLOBAL)

    for learning in learnings:
        if learning.confidence < PROVISIONAL_THRESHOLD:
            result.skipped_count += 1
            logger.debug(
                "Skipping low-confidence learning (%.1f): %s",
                learning.confidence,
                learning.content[:50],
            )
            continue

        # Check for reinforcement of existing provisional learnings
        # Import here to avoid circular import
        from .promotion import check_and_promote_duplicate

        reinforcement = await check_and_promote_duplicate(
            content=learning.content,
            confidence=learning.confidence,
        )

        if reinforcement.found_match:
            if reinforcement.promoted:
                result.canonical_count += 1
                result.stored_count += 1
                logger.info(
                    "Reinforced and promoted existing learning %s",
                    reinforcement.matched_uuid,
                )
            else:
                # Just reinforced, not promoted yet
                result.provisional_count += 1
                result.stored_count += 1
                logger.info(
                    "Reinforced existing learning %s (new confidence: %.1f)",
                    reinforcement.matched_uuid,
                    reinforcement.new_confidence or 0,
                )
            continue  # Don't store duplicate

        # Determine status based on confidence
        status = (
            LearningStatus.CANONICAL
            if learning.confidence >= CANONICAL_THRESHOLD
            else LearningStatus.PROVISIONAL
        )

        # Build source description with status and confidence
        source_description = (
            f"{learning.category} {learning.learning_type.value} "
            f"confidence:{learning.confidence:.0f} status:{status.value}"
        )

        try:
            await service.add_episode(
                content=learning.content,
                source=MemorySource.SYSTEM,
                source_description=source_description,
                reference_time=datetime.now(),
            )

            result.stored_count += 1
            if status == LearningStatus.CANONICAL:
                result.canonical_count += 1
            else:
                result.provisional_count += 1

            logger.info(
                "Stored %s learning (%.1f): %s",
                status.value,
                learning.confidence,
                learning.content[:50],
            )

        except Exception as e:
            logger.error("Failed to store learning: %s", e)
            result.skipped_count += 1

    result.processing_time_ms = int((datetime.now() - start_time).total_seconds() * 1000)

    # Log structured summary
    logger.info(
        "Learning extraction complete: session=%s stored=%d (canonical=%d, provisional=%d) "
        "skipped=%d time=%dms",
        request.session_id,
        result.stored_count,
        result.canonical_count,
        result.provisional_count,
        result.skipped_count,
        result.processing_time_ms,
    )

    return result


def _parse_learnings_json(response_text: str) -> list[ExtractedLearning]:
    """Parse JSON array of learnings from LLM response."""
    # Find JSON array in response (may be wrapped in markdown code blocks)
    import re

    json_match = re.search(r"\[[\s\S]*?\]", response_text)
    if not json_match:
        logger.warning("No JSON array found in learning extraction response")
        return []

    try:
        raw_learnings = json.loads(json_match.group())
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse learnings JSON: %s", e)
        return []

    learnings: list[ExtractedLearning] = []
    for item in raw_learnings:
        if not isinstance(item, dict):
            continue

        try:
            # Map string to enum
            learning_type_str = item.get("learning_type", "pattern").lower()
            learning_type = (
                LearningType(learning_type_str)
                if learning_type_str in [lt.value for lt in LearningType]
                else LearningType.PATTERN
            )

            learnings.append(
                ExtractedLearning(
                    content=item.get("content", ""),
                    learning_type=learning_type,
                    confidence=float(item.get("confidence", 60)),
                    source_quote=item.get("source_quote"),
                    category=item.get("category", "domain_knowledge"),
                )
            )
        except Exception as e:
            logger.warning("Failed to parse learning item: %s - %s", item, e)
            continue

    return learnings[:10]  # Limit to 10 learnings per session
