"""Data models for LLM session analysis."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMAnalysisResult:
    """Combined result from the single session-analysis LLM call."""

    summary: str = ""
    outcome: str = "completed"
    decisions: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    topics: list[str] = field(default_factory=list)
    git_digest: str = ""
    ratings: dict[str, str] = field(default_factory=dict)
