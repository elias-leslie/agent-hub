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
    SessionHeartbeatResult,
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
        session.external_id = "task-123"
        session.client_id = "client-123"
        session.request_source = "codex-transcript-sync"
        session.current_branch = "task-123/main"
        session.provider_metadata = {
            "cwd": "/repo",
            "repo_root": "/repo",
            "working_dir": "/repo/.checkpoints/task-123",
            "host": "devbox",
            "tmux_session_name": "codex-agent-hub",
            "tmux_pane_id": "%11",
            "source_client": "summitflow/codex-session-sync",
            "source_path": "/tmp/codex-session-sync.py",
        }
        session.declared_scope_paths = ["backend/app/services/session_scope.py"]
        session.observed_read_paths = ["backend/app/services/session_ingestion/service.py"]
        session.observed_write_paths = ["backend/app/services/session_scope.py"]
        session.scope_confidence = "declared"
        session.created_at = datetime.now(UTC)
        session.updated_at = datetime.now(UTC)

        with patch(
            "app.api.session_ingestion.upsert_session",
            new_callable=AsyncMock,
            return_value=(
                session,
                SessionUpsertResult(session_id="session-123", created=True),
            ),
        ) as mock_upsert:
            response = await client.post(
                "/api/session-ingestion/sessions/upsert",
                json={
                    "session_id": "session-123",
                    "project_id": "agent-hub",
                    "provider": "codex",
                    "model": "codex/gpt-5.4",
                    "session_type": "agent",
                    "external_id": "task-123",
                    "current_branch": "task-123/main",
                    "cwd": "/repo",
                    "declared_scope_paths": ["backend/app/services/session_scope.py"],
                    "observed_read_paths": ["backend/app/services/session_ingestion/service.py"],
                    "observed_write_paths": ["backend/app/services/session_scope.py"],
                    "scope_confidence": "declared",
                    "provider_metadata": {
                        "repo_root": "/repo",
                        "working_dir": "/repo/.checkpoints/task-123",
                        "host": "devbox",
                        "tmux_session_name": "codex-agent-hub",
                        "tmux_pane_id": "%11",
                    },
                },
                headers={
                    **TEST_HEADERS,
                    "X-Client-Id": "client-123",
                    "X-Request-Source": "codex-transcript-sync",
                    "X-Source-Client": "summitflow/codex-session-sync",
                    "X-Source-Path": "/tmp/codex-session-sync.py",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["created"] is True
        assert data["session"]["id"] == "session-123"
        assert data["session"]["client_id"] == "client-123"
        assert data["session"]["request_source"] == "codex-transcript-sync"
        assert data["session"]["source_client"] == "summitflow/codex-session-sync"
        assert data["session"]["source_path"] == "/tmp/codex-session-sync.py"
        assert data["session"]["declared_scope_paths"] == ["backend/app/services/session_scope.py"]
        assert data["session"]["observed_read_paths"] == [
            "backend/app/services/session_ingestion/service.py"
        ]
        assert data["session"]["observed_write_paths"] == ["backend/app/services/session_scope.py"]
        assert data["session"]["scope_confidence"] == "declared"
        assert data["session"]["repo_root"] == "/repo"
        assert data["session"]["working_dir"] == "/repo/.checkpoints/task-123"
        assert data["session"]["tmux_session_name"] == "codex-agent-hub"
        await_args = mock_upsert.await_args
        assert await_args is not None
        request_payload = await_args.args[1]
        assert request_payload.client_id == "client-123"
        assert request_payload.request_source == "codex-transcript-sync"
        assert request_payload.provider_metadata["source_client"] == "summitflow/codex-session-sync"
        assert request_payload.provider_metadata["source_path"] == "/tmp/codex-session-sync.py"

    @pytest.mark.asyncio
    async def test_upsert_session_endpoint_can_skip_session_snapshot(self, client: AsyncClient) -> None:
        session = MagicMock()
        session.id = "session-123"
        with patch(
            "app.api.session_ingestion.upsert_session",
            new_callable=AsyncMock,
            return_value=(
                session,
                SessionUpsertResult(session_id="session-123", created=True),
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/upsert?include_session=false",
                json={
                    "session_id": "session-123",
                    "project_id": "agent-hub",
                    "provider": "codex",
                    "model": "codex/gpt-5.4",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["created"] is True
        assert data["session"] is None

    @pytest.mark.asyncio
    async def test_upsert_session_endpoint_rejects_overlong_external_id(
        self, client: AsyncClient
    ) -> None:
        response = await client.post(
            "/api/session-ingestion/sessions/upsert",
            json={
                "session_id": "session-123",
                "project_id": "agent-hub",
                "provider": "codex",
                "model": "codex/gpt-5.4",
                "external_id": "x" * 101,
            },
        )

        assert response.status_code == 422
        assert "external_id" in response.text

    @pytest.mark.asyncio
    async def test_heartbeat_session_endpoint(self, client: AsyncClient) -> None:
        """Heartbeat returns updated flag and refreshed session snapshot."""
        session = MagicMock()
        session.id = "session-123"
        session.project_id = "agent-hub"
        session.provider = "anthropic"
        session.model = "claude/sonnet"
        session.status = "active"
        session.agent_slug = "coder"
        session.session_type = "claude_code"
        session.external_id = "task-123"
        session.client_id = "client-234"
        session.request_source = "claude-tool-loop"
        session.current_branch = "task-123/main"
        session.provider_metadata = {
            "cwd": "/repo",
            "repo_root": "/repo",
            "working_dir": "/repo/.checkpoints/task-123",
            "host": "devbox",
            "tmux_session_name": "claude-agent-hub",
            "tmux_pane_id": "%12",
            "source_client": "agent-hub/claude-tools",
            "source_path": "/backend/app/adapters/claude_tools.py",
            "live_activity": {
                "phase": "running_tool",
                "status": "active",
                "summary": "Applying write",
                "last_heartbeat_at": "2026-03-10T14:00:00+00:00",
            },
        }
        session.declared_scope_paths = ["backend/app/services/ownership_inventory.py"]
        session.observed_read_paths = ["backend/app/services/session_live_activity.py"]
        session.observed_write_paths = ["backend/app/services/ownership_inventory.py"]
        session.scope_confidence = "declared"
        session.created_at = datetime.now(UTC)
        session.updated_at = datetime.now(UTC)
        session.last_heartbeat_at = datetime.now(UTC)

        with patch(
            "app.api.session_ingestion.heartbeat_session",
            new_callable=AsyncMock,
            return_value=(
                session,
                SessionHeartbeatResult(session_id="session-123", updated=True),
            ),
        ) as mock_heartbeat:
            response = await client.post(
                "/api/session-ingestion/sessions/session-123/heartbeat",
                json={
                    "cwd": "/repo",
                    "current_branch": "task-123/main",
                    "phase": "running_tool",
                    "status": "active",
                    "summary": "Applying write",
                    "current_tool_name": "Write",
                    "active_read_paths": ["backend/app/services/session_live_activity.py"],
                    "active_write_paths": ["backend/app/services/ownership_inventory.py"],
                    "provider_metadata": {
                        "repo_root": "/repo",
                        "working_dir": "/repo/.checkpoints/task-123",
                        "host": "devbox",
                        "tmux_session_name": "claude-agent-hub",
                        "tmux_pane_id": "%12",
                    },
                },
                headers={
                    **TEST_HEADERS,
                    "X-Client-Id": "client-234",
                    "X-Request-Source": "claude-tool-loop",
                    "X-Source-Client": "agent-hub/claude-tools",
                    "X-Source-Path": "/backend/app/adapters/claude_tools.py",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["updated"] is True
        assert data["session"]["client_id"] == "client-234"
        assert data["session"]["request_source"] == "claude-tool-loop"
        assert data["session"]["source_client"] == "agent-hub/claude-tools"
        assert data["session"]["source_path"] == "/backend/app/adapters/claude_tools.py"
        assert data["session"]["live_activity"]["phase"] == "running_tool"
        assert data["session"]["live_activity"]["last_heartbeat_at"] == "2026-03-10T14:00:00+00:00"
        assert data["session"]["observed_read_paths"] == [
            "backend/app/services/session_live_activity.py"
        ]
        assert data["session"]["observed_write_paths"] == [
            "backend/app/services/ownership_inventory.py"
        ]
        await_args = mock_heartbeat.await_args
        assert await_args is not None
        heartbeat_payload = await_args.args[2]
        assert heartbeat_payload.client_id == "client-234"
        assert heartbeat_payload.request_source == "claude-tool-loop"
        assert heartbeat_payload.provider_metadata["source_client"] == "agent-hub/claude-tools"
        assert heartbeat_payload.provider_metadata["source_path"] == "/backend/app/adapters/claude_tools.py"

    @pytest.mark.asyncio
    async def test_heartbeat_session_endpoint_can_skip_session_snapshot(self, client: AsyncClient) -> None:
        session = MagicMock()
        session.id = "session-123"
        with patch(
            "app.api.session_ingestion.heartbeat_session",
            new_callable=AsyncMock,
            return_value=(
                session,
                SessionHeartbeatResult(session_id="session-123", updated=True),
            ),
        ):
            response = await client.post(
                "/api/session-ingestion/sessions/session-123/heartbeat?include_session=false",
                json={},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "session-123"
        assert data["updated"] is True
        assert data["session"] is None

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
