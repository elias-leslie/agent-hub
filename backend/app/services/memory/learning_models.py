"""Models for learning extraction."""

from enum import StrEnum

from pydantic import BaseModel, Field


class LearningType(StrEnum):
    """Type of learning extracted from a session."""

    VERIFIED = "verified"  # Explicitly confirmed by user (0.95 confidence)
    INFERENCE = "inference"  # Derived from successful task completion (0.80)
    PATTERN = "pattern"  # Observed pattern across interactions (0.60)


class LearningStatus(StrEnum):
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
