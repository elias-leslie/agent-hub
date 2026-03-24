from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.backup_summary import (
    fetch_backup_schedule_line,
    fetch_backup_sources_summary,
    fetch_latest_backup_status_line,
)


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        self.requested_urls.append(url)
        return self._response


class TestFetchLatestBackupStatusLine:
    @pytest.mark.asyncio
    @patch("app.services.backup_summary._read_summitflow_api_url", return_value="http://localhost:8001/api")
    @patch("app.services.backup_summary.httpx.AsyncClient")
    async def test_renders_latest_compact_line(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeResponse(
                {
                    "backups": [
                        {
                            "id": "bkp-123",
                            "status": "completed",
                            "size_bytes": 8912896,
                        }
                    ],
                    "total": 1,
                }
            )
        )
        mock_client_cls.return_value = fake_client

        result = await fetch_latest_backup_status_line("agent-hub")

        assert result == "LATEST bkp-123|completed|8.5MB"
        assert fake_client.requested_urls == ["http://localhost:8001/api/projects/agent-hub/backups?limit=1"]

    @pytest.mark.asyncio
    @patch("app.services.backup_summary._read_summitflow_api_url", return_value="http://localhost:8001/api")
    @patch("app.services.backup_summary.httpx.AsyncClient")
    async def test_returns_no_backups_when_empty(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(_FakeResponse({"backups": [], "total": 0}))
        mock_client_cls.return_value = fake_client

        assert await fetch_latest_backup_status_line("agent-hub") == "NO_BACKUPS"


class TestFetchBackupScheduleLine:
    @pytest.mark.asyncio
    @patch("app.services.backup_summary._read_summitflow_api_url", return_value="http://localhost:8001/api")
    @patch("app.services.backup_summary.httpx.AsyncClient")
    async def test_renders_compact_source_line(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeResponse(
                {
                    "id": "persona-sandbox",
                    "source_type": "workspace",
                    "enabled": True,
                    "frequency": "daily",
                    "retention_days": 30,
                    "name": "Persona Sandbox",
                }
            )
        )
        mock_client_cls.return_value = fake_client

        result = await fetch_backup_schedule_line("persona-sandbox")

        assert result == "persona-sandbox      workspace  enabled  daily    30   Persona Sandbox"
        assert fake_client.requested_urls == ["http://localhost:8001/api/backup-sources/persona-sandbox"]


class TestFetchBackupSourcesSummary:
    @pytest.mark.asyncio
    @patch("app.services.backup_summary._read_summitflow_api_url", return_value="http://localhost:8001/api")
    @patch("app.services.backup_summary.httpx.AsyncClient")
    async def test_renders_compact_sources_block(
        self,
        mock_client_cls: MagicMock,
        _mock_read_api_url: MagicMock,
    ) -> None:
        fake_client = _FakeAsyncClient(
            _FakeResponse(
                [
                    {
                        "id": "persona-sandbox",
                        "source_type": "workspace",
                        "enabled": True,
                        "frequency": "daily",
                        "retention_days": 30,
                        "name": "Persona Sandbox",
                    },
                    {
                        "id": "agent-hub",
                        "source_type": "project",
                        "enabled": False,
                        "frequency": "weekly",
                        "retention_days": 14,
                        "name": "Agent Hub",
                    },
                ]
            )
        )
        mock_client_cls.return_value = fake_client

        result = await fetch_backup_sources_summary("workspace")

        assert result == (
            "SOURCES[2]\n"
            "persona-sandbox      workspace  enabled  daily    30   Persona Sandbox\n"
            "agent-hub            project    disabled weekly   14   Agent Hub"
        )
        assert fake_client.requested_urls == ["http://localhost:8001/api/backup-sources?source_type=workspace"]
