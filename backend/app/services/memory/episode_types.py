"""Episode data types and structures."""

from dataclasses import dataclass
from datetime import datetime

from graphiti_core.nodes import EpisodeType

from .episode_helpers import InjectionTier
from .service import MemoryCategory, MemoryScope


@dataclass
class FormattedEpisode:
    """Formatted episode ready for Graphiti ingestion."""

    name: str
    episode_body: str
    source_type: EpisodeType
    source_description: str
    reference_time: datetime
    group_id: str
    # Metadata for tracking (not sent to Graphiti directly)
    category: MemoryCategory
    scope: MemoryScope
    tier: InjectionTier
    is_golden: bool
    is_anti_pattern: bool
    confidence: int  # 0-100
