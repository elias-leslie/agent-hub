"""Shared pytest fixtures and configuration.

Integration tests are skipped by default. Run them with:
    pytest -m integration

Or run all tests:
    pytest --run-integration
"""

import pytest

from app.main import app


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running services)",
    )


def pytest_configure(config):
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires running services)"
    )


def pytest_collection_modifyitems(config, items):
    """Skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration"):
        # Run all tests
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


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
