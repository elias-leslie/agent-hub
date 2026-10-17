"""Signal loaders for the persona honing loop."""
from __future__ import annotations


async def _load_recent_improvement_signals(project_id: str) -> str | None:
    """Return recent combined improvement evidence for the honing prompt."""
    from app.services.improvement_signals import build_improvement_signal_digest

    review = await build_improvement_signal_digest(
        project_id=project_id, primary_agent_slug="persona", days_back=7, include_team=True,
    )
    return review.strip() or None
