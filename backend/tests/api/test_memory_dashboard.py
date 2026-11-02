"""Tests for memory dashboard summary-context persistence."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.memory_dashboard import _store_summary_request_context


@pytest.mark.asyncio
async def test_store_summary_request_context_persists_transcript_provenance() -> None:
    """Summary requests should retain transcript provenance for later reanalysis."""
    session = SimpleNamespace(
        provider_metadata={"cache": {"total_cache_read_tokens": 42}},
    )
    mock_result = SimpleNamespace(scalar_one_or_none=lambda: session)
    mock_db = AsyncMock()
    mock_db.execute.return_value = mock_result
    mock_factory = MagicMock()
    mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_db)
    mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

    with patch("app.api.memory_dashboard._get_session_factory", return_value=mock_factory):
        await _store_summary_request_context(
            "session-123",
            branch="main",
            transcript_path="/tmp/codex-session.jsonl",
            git_context="abc1234 feat: persist transcript context",
        )

    assert session.provider_metadata == {
        "cache": {"total_cache_read_tokens": 42},
        "summary_context": {
            "branch": "main",
            "transcript_path": "/tmp/codex-session.jsonl",
            "git_context": "abc1234 feat: persist transcript context",
        },
    }
    mock_db.commit.assert_awaited_once()
