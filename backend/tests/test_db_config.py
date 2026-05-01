from __future__ import annotations

from unittest.mock import patch

from app import db


def test_engine_uses_configured_pool_limits(monkeypatch) -> None:
    db._get_engine.cache_clear()
    monkeypatch.setattr("app.db.settings.agent_hub_db_url", "postgresql://user:pass@localhost/db")
    monkeypatch.setattr("app.db.settings.debug", False)
    monkeypatch.setattr("app.db.settings.agent_hub_db_pool_size", 4)
    monkeypatch.setattr("app.db.settings.agent_hub_db_max_overflow", 1)
    monkeypatch.setattr("app.db.settings.agent_hub_db_pool_timeout", 7)
    monkeypatch.setattr("app.db.settings.agent_hub_db_pool_recycle", 99)

    with patch("app.db.create_async_engine", return_value=object()) as mock_create:
        db._get_engine()

    db._get_engine.cache_clear()
    mock_create.assert_called_once_with(
        "postgresql+asyncpg://user:pass@localhost/db",
        echo=False,
        pool_pre_ping=True,
        pool_size=4,
        max_overflow=1,
        pool_timeout=7,
        pool_recycle=99,
    )
