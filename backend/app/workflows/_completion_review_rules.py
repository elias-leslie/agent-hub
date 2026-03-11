"""Shared prompt rules for benchmarked completion-review behavior."""

from __future__ import annotations

from app.services.persona_prompt_service import render_completion_review_rules as _render_rules


async def render_completion_review_rules(*, header: str = "Rules") -> str:
    return await _render_rules(header=header)
