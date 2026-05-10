"""DB-backed singleton policy for the strict-Caveman compactness gate.

Thresholds were originally module-level constants in ``services/compactness.py``.
They now live in ``compactness_policy`` (id=1, single row) so the same caps are
read by API saves, the CLI, and any worker — single source of truth.

The validator path is sync and called from many places, so this module keeps
an in-process cache that is hydrated once on startup and invalidated by the
PUT endpoint. Falls back to module defaults if the cache is empty (e.g. when
the validator runs in a context that never hydrated, like one-off scripts).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from app.models.compactness_policy import CompactnessPolicy


@dataclass(frozen=True)
class CompactnessPolicyValues:
    memory_max_chars: int = 280
    memory_max_lines: int = 4
    prompt_max_tokens: int = 350
    prompt_max_lines: int = 80
    max_sentence_words: int = 24
    max_avg_sentence_words: int = 16
    avg_sentence_min_words: int = 120
    max_article_ratio_permille: int = 85
    article_ratio_min_words: int = 80

    @property
    def max_article_ratio(self) -> float:
        return self.max_article_ratio_permille / 1000.0


DEFAULTS = CompactnessPolicyValues()

_cache: CompactnessPolicyValues | None = None


def get_policy() -> CompactnessPolicyValues:
    """Return the active policy (sync). Falls back to defaults if not hydrated."""
    return _cache or DEFAULTS


def _set_cache(values: CompactnessPolicyValues) -> None:
    global _cache
    _cache = values


def invalidate_cache() -> None:
    """Drop the cached policy. Next get_policy() call will return defaults
    until load_policy_from_db runs again."""
    global _cache
    _cache = None


async def load_policy_from_db(db: AsyncSession) -> CompactnessPolicyValues:
    """Hydrate the cache from the singleton row. Called on app startup."""
    from app.models.compactness_policy import CompactnessPolicy

    row = await db.get(CompactnessPolicy, 1)
    if row is None:
        _set_cache(DEFAULTS)
        return DEFAULTS
    values = _row_to_values(row)
    _set_cache(values)
    return values


class CompactnessPolicyResponse(BaseModel):
    memory_max_chars: int
    memory_max_lines: int
    prompt_max_tokens: int
    prompt_max_lines: int
    max_sentence_words: int
    max_avg_sentence_words: int
    avg_sentence_min_words: int
    max_article_ratio_permille: int
    article_ratio_min_words: int


class CompactnessPolicyUpdate(BaseModel):
    """Partial update — any field omitted leaves the existing value."""

    memory_max_chars: int | None = Field(default=None, ge=1)
    memory_max_lines: int | None = Field(default=None, ge=1)
    prompt_max_tokens: int | None = Field(default=None, ge=1)
    prompt_max_lines: int | None = Field(default=None, ge=1)
    max_sentence_words: int | None = Field(default=None, ge=1)
    max_avg_sentence_words: int | None = Field(default=None, ge=1)
    avg_sentence_min_words: int | None = Field(default=None, ge=1)
    max_article_ratio_permille: int | None = Field(default=None, ge=0, le=1000)
    article_ratio_min_words: int | None = Field(default=None, ge=1)


async def get_compactness_policy(db: AsyncSession) -> CompactnessPolicyResponse:
    from app.models.compactness_policy import CompactnessPolicy

    row = await db.get(CompactnessPolicy, 1)
    if row is None:
        return CompactnessPolicyResponse(**DEFAULTS.__dict__)
    return _row_to_response(row)


async def update_compactness_policy(
    db: AsyncSession,
    payload: CompactnessPolicyUpdate,
) -> CompactnessPolicyResponse:
    from app.models.compactness_policy import CompactnessPolicy

    row = await db.get(CompactnessPolicy, 1)
    if row is None:
        row = CompactnessPolicy(id=1, **DEFAULTS.__dict__)
        db.add(row)
    for field, value in payload.model_dump(exclude_none=True).items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    _set_cache(_row_to_values(row))
    return _row_to_response(row)


def _row_to_values(row: CompactnessPolicy) -> CompactnessPolicyValues:
    return CompactnessPolicyValues(
        memory_max_chars=row.memory_max_chars,
        memory_max_lines=row.memory_max_lines,
        prompt_max_tokens=row.prompt_max_tokens,
        prompt_max_lines=row.prompt_max_lines,
        max_sentence_words=row.max_sentence_words,
        max_avg_sentence_words=row.max_avg_sentence_words,
        avg_sentence_min_words=row.avg_sentence_min_words,
        max_article_ratio_permille=row.max_article_ratio_permille,
        article_ratio_min_words=row.article_ratio_min_words,
    )


def _row_to_response(row: CompactnessPolicy) -> CompactnessPolicyResponse:
    return CompactnessPolicyResponse(
        memory_max_chars=row.memory_max_chars,
        memory_max_lines=row.memory_max_lines,
        prompt_max_tokens=row.prompt_max_tokens,
        prompt_max_lines=row.prompt_max_lines,
        max_sentence_words=row.max_sentence_words,
        max_avg_sentence_words=row.max_avg_sentence_words,
        avg_sentence_min_words=row.avg_sentence_min_words,
        max_article_ratio_permille=row.max_article_ratio_permille,
        article_ratio_min_words=row.article_ratio_min_words,
    )
