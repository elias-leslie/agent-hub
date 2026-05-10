"""Singleton table holding the strict-Caveman gate thresholds."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class CompactnessPolicy(Base):
    """Tunable thresholds for compactness validation. Singleton row at id=1."""

    __tablename__ = "compactness_policy"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    memory_max_chars: Mapped[int] = mapped_column(Integer, nullable=False)
    memory_max_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_max_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_max_lines: Mapped[int] = mapped_column(Integer, nullable=False)
    max_sentence_words: Mapped[int] = mapped_column(Integer, nullable=False)
    max_avg_sentence_words: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_sentence_min_words: Mapped[int] = mapped_column(Integer, nullable=False)
    # Permille (parts per thousand). 85 == 8.5%.
    max_article_ratio_permille: Mapped[int] = mapped_column(Integer, nullable=False)
    article_ratio_min_words: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
