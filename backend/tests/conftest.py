"""Shared pytest fixtures and configuration.

Integration tests are skipped by default. Run them with:
    pytest -m integration

Or run all tests:
    pytest --run-integration

IMPORTANT: All tests that call LLM adapters MUST mock them.
The block_real_llm_calls fixture (autouse=True) will raise an error if
any test tries to make a real API call without proper mocking.

CRITICAL: Tests NEVER touch production database. Database is mocked by default,
and integration tests must use agent_hub_test database.
"""

from __future__ import annotations

# =============================================================================
# PRODUCTION DATABASE GUARD - MUST RUN BEFORE ANY APP IMPORTS
# =============================================================================
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Load env vars FIRST
_env_file = Path.home() / ".env.local"
if _env_file.exists():
    load_dotenv(_env_file)

_db_url = os.environ.get("AGENT_HUB_DB_URL", "")
_test_db_url = os.environ.get("TEST_AGENT_HUB_DB_URL", "")

# Hatchet SDK requires a token at client construction time (triggered by workflow
# decorators at import time).  Set a dummy token so tests can import workflow modules
# without a running Hatchet engine.
os.environ.setdefault(
    "HATCHET_CLIENT_TOKEN",
    "eyJhbGciOiAiSFMyNTYiLCAidHlwIjogIkpXVCJ9."
    "eyJzZXJ2ZXJfdXJsIjogImh0dHA6Ly9sb2NhbGhvc3Q6ODg4OCIsICJncnBjX2Jyb2FkY2FzdF9hZGRyZXNzIjogImxvY2FsaG9zdDo3MDc3IiwgInN1YiI6ICJ0ZXN0IiwgImlhdCI6IDE1MTYyMzkwMjJ9."
    "dGVzdC1zaWduYXR1cmUtcGFkZGluZyE",
)
os.environ.setdefault("HATCHET_CLIENT_TLS_STRATEGY", "none")

# Internal service secret must match TEST_HEADERS for access control bypass.
# Force override (load_dotenv may have already set a production value).
os.environ["INTERNAL_SERVICE_SECRET"] = "agent-hub-internal-v1"

# If TEST_AGENT_HUB_DB_URL is set, override AGENT_HUB_DB_URL BEFORE any app imports
if _test_db_url:
    os.environ["AGENT_HUB_DB_URL"] = _test_db_url

# =============================================================================
# NOW safe to import from app modules
# =============================================================================

from collections.abc import AsyncGenerator, Generator  # noqa: E402
from typing import Any  # noqa: E402
from unittest.mock import AsyncMock, MagicMock, patch  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from httpx import Response  # noqa: E402

from app.main import app  # noqa: E402


def pytest_addoption(parser: pytest.Parser) -> None:
    """Add custom command line options."""
    parser.addoption(
        "--run-integration",
        action="store_true",
        default=False,
        help="Run integration tests (requires running services)",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Block tests from running against production database and register markers."""
    db_url = os.environ.get("AGENT_HUB_DB_URL", "")
    test_db_url = os.environ.get("TEST_AGENT_HUB_DB_URL", "")

    # For integration tests, check if pointing at production
    is_production = "/agent_hub" in db_url and "/agent_hub_test" not in db_url and not test_db_url

    if is_production and config.getoption("--run-integration", default=False):
        print("\n" + "=" * 70, file=sys.stderr)
        print(
            "FATAL: REFUSING TO RUN INTEGRATION TESTS AGAINST PRODUCTION DATABASE", file=sys.stderr
        )
        print("=" * 70, file=sys.stderr)
        print(f"\nAGENT_HUB_DB_URL points to: {db_url}", file=sys.stderr)
        print("\nIntegration tests require:", file=sys.stderr)
        print("  TEST_AGENT_HUB_DB_URL in ~/.env.local pointing to agent_hub_test", file=sys.stderr)
        print("\nTo fix, add to ~/.env.local:", file=sys.stderr)
        print(
            "  TEST_AGENT_HUB_DB_URL=postgresql://agent_hub_app:...@localhost:5432/agent_hub_test",
            file=sys.stderr,
        )
        print("=" * 70 + "\n", file=sys.stderr)
        pytest.exit(
            "BLOCKED: Cannot run integration tests against production database", returncode=1
        )

    # Register markers
    config.addinivalue_line(
        "markers", "unit: marks tests as unit tests (fast, no external dependencies)"
    )
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with -m not slow)")
    config.addinivalue_line(
        "markers", "integration: mark test as integration test (requires running services)"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Skip integration tests unless --run-integration is passed."""
    if config.getoption("--run-integration"):
        # Run all tests
        return

    skip_integration = pytest.mark.skip(reason="need --run-integration option to run")
    for item in items:
        if "integration" in item.keywords:
            item.add_marker(skip_integration)


# Standard headers for test requests - identifies them as pytest in Admin UI
# Also includes the internal bypass header for access control middleware
TEST_HEADERS = {
    "X-Source-Client": "pytest",
    "X-Source-Path": "/tests",
    "X-Agent-Hub-Internal": "agent-hub-internal-v1",
}


class APITestClient(TestClient):
    """TestClient wrapper that auto-adds headers for access control bypass.

    All requests through this client will include:
    - X-Source-Client: pytest (for tracking)
    - X-Source-Path: /tests (for tracking)
    - X-Agent-Hub-Internal: agent-hub-internal-v1 (bypasses access control)
    """

    def request(self, method: str, url: str, **kwargs: Any) -> Response:  # type: ignore[override]
        """Add test headers to all requests."""
        headers = kwargs.get("headers") or {}
        # Don't override if explicitly set
        for key, value in TEST_HEADERS.items():
            if key not in headers:
                headers[key] = value
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture
def test_client() -> Generator[TestClient]:
    """Create FastAPI test client (basic, no headers)."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def api_client() -> Generator[APITestClient]:
    """Create FastAPI test client with source headers for API tests.

    Use this fixture for any test that calls API endpoints protected by
    the kill switch middleware. The client automatically adds:
    - X-Source-Client: pytest
    - X-Source-Path: /tests

    Tests using this fixture will be visible in the Agent Hub Admin UI
    under the 'pytest' client, allowing tracking and blocking of test traffic.
    """
    with APITestClient(app) as client:
        yield client


async def _null_db() -> AsyncGenerator[None]:
    """Return None for database dependency - prevents session creation in tests."""
    yield None


@pytest.fixture(autouse=True)
def setup_test_app_state() -> Generator[None]:
    """Set up app state for tests.

    This fixture:
    1. Clears any existing dependency overrides
    2. Disables database sessions to prevent polluting the sessions table
       (The /api/complete endpoint checks `if db:` before creating sessions)

    The kill switch middleware is NOT bypassed - it checks headers before
    accessing the database, and has fail-open behavior for db errors.

    Tests that actually need database access should use:
        @pytest.fixture
        def enable_db(self):
            from app.db import get_db
            app.dependency_overrides.pop(get_db, None)
            yield
    """
    from app.db import get_db

    # Clear existing overrides first
    app.dependency_overrides.clear()

    # Disable database session creation
    app.dependency_overrides[get_db] = _null_db

    yield

    # Clean up
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def clear_db_cache() -> Generator[None]:
    """Clear database cache before each test to avoid event loop issues."""
    from app import db

    db._get_engine.cache_clear()
    db._get_session_factory.cache_clear()
    yield
    db._get_engine.cache_clear()
    db._get_session_factory.cache_clear()


@pytest.fixture(autouse=True)
def clear_hatchet_cache() -> Generator[None]:
    """Clear Hatchet client cache so tests get fresh instances."""
    from app.hatchet_app import get_hatchet

    get_hatchet.cache_clear()
    yield
    get_hatchet.cache_clear()


class RealAPICallError(Exception):
    """Raised when a test tries to make a real API call without proper mocking."""

    pass


def _raise_real_api_error(*args: Any, **kwargs: Any) -> None:
    """Raise error when real API is called without mocking."""
    raise RealAPICallError(
        "Test attempted to make a real LLM API call! "
        "Mock complete_internal() or the app.llm provider stream in your test."
    )


@pytest.fixture(autouse=True)
def block_real_llm_calls(request: pytest.FixtureRequest) -> Generator[None]:
    """Block real LLM API calls unless test is marked as integration.

    This safety net fixture ensures tests don't accidentally make real API calls.
    Tests marked with @pytest.mark.integration bypass this protection.

    To make real API calls in integration tests:
        @pytest.mark.integration
        def test_real_api():
            ...
    """
    # Skip blocking for integration tests that explicitly need real calls
    if "integration" in request.keywords:
        yield
        return

    # Patch the actual API client libraries to raise errors if called
    with (
        patch("anthropic.AsyncAnthropic") as mock_anthropic,
        patch("google.genai.Client") as mock_genai,
    ):
        # Configure mocks to raise clear errors if not properly mocked
        mock_anthropic.return_value.messages.create = AsyncMock(side_effect=_raise_real_api_error)
        mock_genai.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_raise_real_api_error
        )
        yield



def create_mock_db_session() -> AsyncMock:
    """Create a mock database session with sensible defaults.

    Returns a mock that:
    - execute() returns empty results by default
    - add()/commit()/refresh() work as no-ops
    - refresh() sets common timestamp fields (created_at, updated_at)
    - Can be customized by tests as needed
    """
    from datetime import UTC, datetime

    mock_session = AsyncMock()

    # Default execute returns empty results
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None
    mock_result.scalars.return_value.all.return_value = []
    mock_result.all.return_value = []
    mock_result.fetchall.return_value = []
    mock_result.scalar.return_value = 0
    mock_session.execute.return_value = mock_result

    # add/commit work as no-ops
    mock_session.add = MagicMock()
    mock_session.commit = AsyncMock()
    mock_session.close = AsyncMock()

    # refresh sets common timestamp fields like the real database would
    async def mock_refresh(obj: Any) -> None:
        now = datetime.now(UTC)
        if hasattr(obj, "created_at") and obj.created_at is None:
            obj.created_at = now
        if hasattr(obj, "updated_at") and obj.updated_at is None:
            obj.updated_at = now
        if hasattr(obj, "id") and obj.id is None:
            obj.id = 1

    mock_session.refresh = mock_refresh

    return mock_session


@pytest.fixture
def mock_db_session() -> Generator[AsyncMock]:
    """Provide a mock database session for tests that need it.

    Usage:
        def test_something(self, mock_db_session):
            # mock_db_session is already set up in app.dependency_overrides
            response = client.get("/api/some-endpoint")
    """
    from app.db import get_db

    mock_session = create_mock_db_session()

    async def mock_get_db() -> AsyncGenerator[AsyncMock]:
        yield mock_session

    # Override the null db with our mock
    app.dependency_overrides[get_db] = mock_get_db
    yield mock_session
    # Restore null db (will be cleaned up by setup_test_app_state anyway)
    app.dependency_overrides[get_db] = _null_db
