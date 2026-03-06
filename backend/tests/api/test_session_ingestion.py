"""Tests for the canonical session ingestion API."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.session_ingestion import (
    AppendNormalizedEventsResult,
    FinalizeSessionResult,
    SessionUpsertResult,
)
from tests.conftest import TEST_HEADERS


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient]:
    """Async test client with source headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac


class TestSessionIngestionAPI:
    """Tests for `/api/session-ingestion/...` endpoints."""

    @pytest.mark.asyncio
    async def test_upsert_session_endpoint(self, client: AsyncClient) -> None:
        """Upsert returns created flag and session snapshot."""
        session = MagicMock()
        session.id = "session-123"
        session.project_id = "agent-hub"
        session.provider = "codex"
        session.model = "codex/gpt-5.4"
        session.status = "active"
        session.agent_slug = None
        session.session_type = "agent"
        session.created_at = datetime.now(UTC)
        session.updated_at = datetime.now(UTC)

        with patch(
            "app.api.session_ingestion.upsert_session",
            new_callable=AsyncMock,
            return_value=(
                session,
                SessionUpsertResult(session_id="session-123", created=True),
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/upsert",
                json={
                    "session_id": "session-123",
                    "project_id": "agent-hub",
                    "provider": "codex",
                    "model": "codex/gpt-5.4",
                    "session_type": "agent",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["created"] is True
        assert data["session"]["id"] == "session-123"

    @pytest.mark.asyncio
    async def test_append_events_endpoint(self, client: AsyncClient) -> None:
        """Append returns event counts and last sequence."""
        with (
            patch(
                "app.api.session_ingestion.get_session_or_404",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.session_ingestion.append_normalized_events",
                new_callable=AsyncMock,
                return_value=AppendNormalizedEventsResult(
                    session_id="session-123",
                    events_appended=2,
                    last_turn=3,
                    last_sequence=9,
                    event_ids=["evt-1", "evt-2"],
                ),
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/session-123/events/append",
                json={
                    "events": [
                        {"event_type": "user_message", "role": "user", "content": "hi"},
                        {"event_type": "assistant_message", "role": "assistant", "content": "hello"},
                    ]
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["events_appended"] == 2
        assert data["last_sequence"] == 9
        assert data["event_ids"] == ["evt-1", "evt-2"]

    @pytest.mark.asyncio
    async def test_finalize_session_endpoint(self, client: AsyncClient) -> None:
        """Finalize endpoint delegates to the canonical finalizer."""
        with patch(
            "app.api.session_ingestion.finalize_session",
            new_callable=AsyncMock,
            return_value=FinalizeSessionResult(
                session_id="session-123",
                citations_found=3,
                citations_credited=2,
                feedback_created=1,
                summary_stored=True,
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/session-123/finalize",
                json={"transcript_path": "/tmp/session.jsonl"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["citations_credited"] == 2
        assert data["summary_stored"] is True

    @pytest.mark.asyncio
    async def test_transcript_events_endpoint(self, client: AsyncClient) -> None:
        """Transcript ingest endpoint returns checkpointed append results."""
        with (
            patch(
                "app.api.session_ingestion.get_session_or_404",
                new_callable=AsyncMock,
            ),
            patch(
                "app.api.session_ingestion.ingest_transcript_events",
                new_callable=AsyncMock,
                return_value={
                    "session_id": "session-123",
                    "provider": "codex",
                    "transcript_path": "/tmp/session.jsonl",
                    "events_appended": 4,
                    "events_skipped": 0,
                    "last_turn": 1,
                    "last_sequence": 4,
                    "event_ids": ["evt-1", "evt-2"],
                    "next_checkpoint": "4",
                    "boundaries": ["opened"],
                },
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/session-123/transcript-events",
                json={
                    "provider": "codex",
                    "transcript_path": "/tmp/session.jsonl",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["events_appended"] == 4
        assert data["next_checkpoint"] == "4"
        assert data["boundaries"] == ["opened"]
