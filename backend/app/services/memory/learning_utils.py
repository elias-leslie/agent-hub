"""Utility functions for learning extraction."""

import json
import logging
import re

from .learning_models import ExtractedLearning, LearningType

logger = logging.getLogger(__name__)


def parse_learnings_json(response_text: str) -> list[ExtractedLearning]:
    """Parse JSON array of learnings from LLM response."""
    # Find JSON array in response (may be wrapped in markdown code blocks)
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
