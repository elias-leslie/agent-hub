"""Data models for episode creation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .budget import count_tokens
from .ingestion_config import IngestionConfig
from .service import MemorySource


@dataclass
class CreateResult:
    """Result of an episode creation attempt."""

    success: bool
    uuid: str | None = None
    deduplicated: bool = False
    validation_error: str | None = None


@dataclass
class BatchEpisodeRequest:
    """Request for batch episode creation.

    Attributes:
        content: The episode content/body
        name: Episode name (slug-like identifier)
        config: Ingestion configuration (defaults to LEARNING profile)
        source_description: Human-readable source description
        reference_time: When the episode occurred (defaults to now)
        source: Source type for the episode
        injection_tier: Explicit tier override (mandate/guardrail/reference)
        summary: Optional summary for the episode
        metadata: Optional structured metadata to store with the episode
    """

    content: str
    name: str
    config: IngestionConfig | None = None
    source_description: str | None = None
    reference_time: datetime | None = None
    source: MemorySource = field(default_factory=lambda: MemorySource.SYSTEM)
    injection_tier: str | None = None
    summary: str | None = None
    context_kind: str | None = None
    applicability: dict[str, object] | None = None
    tags: list[str] | None = None
    metadata: dict[str, object] | None = None

    @property
    def token_count(self) -> int:
        """Estimated token count for this episode."""
        return count_tokens(self.content)


@dataclass
class BatchCreateResult:
    """Result of batch episode creation.

    Attributes:
        results: List of individual CreateResult for each episode
        total: Total number of episodes requested
        successful: Number of successfully created episodes
        deduplicated: Number of episodes skipped due to deduplication
        failed: Number of episodes that failed validation or creation
        batches_used: Number of token-aware batches used
    """

    results: list[CreateResult] = field(default_factory=list)
    total: int = 0
    successful: int = 0
    deduplicated: int = 0
    failed: int = 0
    batches_used: int = 0
