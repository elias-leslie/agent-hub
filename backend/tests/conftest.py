"""Shared pytest fixtures and configuration."""

import pytest

from app.main import app


@pytest.fixture(autouse=True)
def clear_app_state():
    """Clear app state before each test."""
    # Clear dependency overrides
    app.dependency_overrides.clear()
    yield
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_db_cache():
    """Clear database cache before each test to avoid event loop issues."""
    from app import db
    db._get_engine.cache_clear()
    db._get_session_factory.cache_clear()
    yield
    db._get_engine.cache_clear()
    db._get_session_factory.cache_clear()
