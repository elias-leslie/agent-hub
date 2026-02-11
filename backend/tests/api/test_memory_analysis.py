"""Tests for memory analysis API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services.memory.session_analysis import AnalysisResult, TaskOutcomeResult
from tests.conftest import TEST_HEADERS


@pytest.fixture
async def client():
    """Async test client with source headers."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers=TEST_HEADERS,
    ) as ac:
        yield ac


class TestAnalyzeEndpoint:
    """Tests for POST /api/memory/sessions/{session_id}/analyze."""

    @pytest.mark.asyncio
    async def test_analyze_session_with_prefixes(self, client: AsyncClient):
        """CC path: send prefixes, get credited count."""
        with patch(
            "app.api.memory_analysis.analyze_session",
            new_callable=AsyncMock,
            return_value=AnalysisResult(
                session_id="test-session",
                citations_found=3,
                citations_credited=2,
            ),
        ):
            # Import from the correct location (lazy import in endpoint)
            with patch(
                "app.services.memory.session_analysis.analyze_session",
                new_callable=AsyncMock,
                return_value=AnalysisResult(
                    session_id="test-session",
                    citations_found=3,
                    citations_credited=2,
                ),
            ):
                response = await client.post(
                    "/api/memory/sessions/test-session/analyze",
                    json={"citation_prefixes": ["abc12345", "def67890", "11223344"]},
                )

        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session"
        assert data["citations_found"] == 3
        assert data["citations_credited"] == 2

    @pytest.mark.asyncio
    async def test_analyze_session_no_body(self, client: AsyncClient):
        """API path: no body triggers event scanning."""
        with patch(
            "app.services.memory.session_analysis.analyze_session",
            new_callable=AsyncMock,
            return_value=AnalysisResult(
                session_id="test-session",
                citations_found=1,
                citations_credited=1,
            ),
        ):
            response = await client.post("/api/memory/sessions/test-session/analyze")

        assert response.status_code == 200
        data = response.json()
        assert data["citations_found"] == 1

    @pytest.mark.asyncio
    async def test_analyze_session_error_returns_500(self, client: AsyncClient):
        """Internal error returns 500."""
        with patch(
            "app.services.memory.session_analysis.analyze_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Neo4j down"),
        ):
            response = await client.post("/api/memory/sessions/test-session/analyze")

        assert response.status_code == 500


class TestTaskOutcomeEndpoint:
    """Tests for POST /api/memory/sessions/{session_id}/task-outcome."""

    @pytest.mark.asyncio
    async def test_task_outcome_success(self, client: AsyncClient):
        """Report successful task outcome."""
        with patch(
            "app.services.memory.session_analysis.process_task_outcome",
            new_callable=AsyncMock,
            return_value=TaskOutcomeResult(
                session_id="test-session",
                task_succeeded=True,
                metrics_updated=1,
                memories_credited=5,
            ),
        ):
            response = await client.post(
                "/api/memory/sessions/test-session/task-outcome",
                json={"succeeded": True, "task_id": "task-123"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["task_succeeded"] is True
        assert data["memories_credited"] == 5

    @pytest.mark.asyncio
    async def test_task_outcome_failure(self, client: AsyncClient):
        """Report failed task outcome."""
        with patch(
            "app.services.memory.session_analysis.process_task_outcome",
            new_callable=AsyncMock,
            return_value=TaskOutcomeResult(
                session_id="test-session",
                task_succeeded=False,
                metrics_updated=1,
                memories_credited=0,
            ),
        ):
            response = await client.post(
                "/api/memory/sessions/test-session/task-outcome",
                json={"succeeded": False},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["task_succeeded"] is False
        assert data["memories_credited"] == 0


class TestTaskOutcomeByTaskEndpoint:
    """Tests for POST /api/memory/task-outcome."""

    @pytest.mark.asyncio
    async def test_task_outcome_by_task_processes_sessions(self, client: AsyncClient):
        """Task-scoped endpoint finds and processes all sessions."""
        with (
            patch(
                "app.services.memory.session_analysis.find_sessions_for_task",
                new_callable=AsyncMock,
                return_value=["session-1", "session-2"],
            ),
            patch(
                "app.services.memory.session_analysis.process_task_outcome",
                new_callable=AsyncMock,
                side_effect=[
                    TaskOutcomeResult(
                        session_id="session-1",
                        task_succeeded=True,
                        metrics_updated=1,
                        memories_credited=3,
                    ),
                    TaskOutcomeResult(
                        session_id="session-2",
                        task_succeeded=True,
                        metrics_updated=1,
                        memories_credited=2,
                    ),
                ],
            ),
        ):
            response = await client.post(
                "/api/memory/task-outcome",
                json={"task_id": "task-abc", "succeeded": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["task_id"] == "task-abc"
        assert data["sessions_processed"] == 2
        assert data["total_metrics_updated"] == 2
        assert data["total_memories_credited"] == 5

    @pytest.mark.asyncio
    async def test_task_outcome_by_task_no_sessions(self, client: AsyncClient):
        """No associated sessions returns zero counts."""
        with patch(
            "app.services.memory.session_analysis.find_sessions_for_task",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.post(
                "/api/memory/task-outcome",
                json={"task_id": "task-orphan", "succeeded": True},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sessions_processed"] == 0
        assert data["total_memories_credited"] == 0

    @pytest.mark.asyncio
    async def test_task_outcome_passes_project_id_fallback(self, client: AsyncClient):
        """project_id and started_at are forwarded to find_sessions_for_task."""
        with (
            patch(
                "app.services.memory.session_analysis.find_sessions_for_task",
                new_callable=AsyncMock,
                return_value=["session-5"],
            ) as mock_find,
            patch(
                "app.services.memory.session_analysis.process_task_outcome",
                new_callable=AsyncMock,
                return_value=TaskOutcomeResult(
                    session_id="session-5",
                    task_succeeded=True,
                    metrics_updated=1,
                    memories_credited=4,
                ),
            ),
        ):
            response = await client.post(
                "/api/memory/task-outcome",
                json={
                    "task_id": "task-xyz",
                    "succeeded": True,
                    "project_id": "agent-hub",
                    "started_at": "2026-02-10T12:00:00+00:00",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["sessions_processed"] == 1
        assert data["total_memories_credited"] == 4
        mock_find.assert_called_once_with(
            "task-xyz",
            project_id="agent-hub",
            started_at="2026-02-10T12:00:00+00:00",
        )
