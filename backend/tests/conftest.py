"""Shared pytest fixtures and configuration.

Integration tests are skipped by default. Run them with:
    pytest -m integration

Or run all tests:
    pytest --run-integration

IMPORTANT: All tests that call LLM adapters MUST mock them.
The block_real_llm_calls fixture (autouse=True) will raise an error if
any test tries to make a real API call without proper mocking.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

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


# Standard headers for test requests - identifies them as pytest in Admin UI
TEST_HEADERS = {
    "X-Source-Client": "pytest",
    "X-Source-Path": "/tests",
}


class APITestClient(TestClient):
    """TestClient wrapper that auto-adds source headers for kill switch compliance.

    All requests through this client will include X-Source-Client: pytest
    and X-Source-Path: /tests headers, making them trackable in the Admin UI.
    """

    def request(self, method: str, url: str, **kwargs):
        """Add test headers to all requests."""
        headers = kwargs.get("headers") or {}
        # Don't override if explicitly set
        for key, value in TEST_HEADERS.items():
            if key not in headers:
                headers[key] = value
        kwargs["headers"] = headers
        return super().request(method, url, **kwargs)


@pytest.fixture
def test_client():
    """Create FastAPI test client (basic, no headers)."""
    with TestClient(app) as client:
        yield client


@pytest.fixture
def api_client():
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


async def _null_db():
    """Return None for database dependency - prevents session creation in tests."""
    yield None


@pytest.fixture(autouse=True)
def setup_test_app_state():
    """Set up app state for tests.

    This fixture:
    1. Clears any existing dependency overrides
    2. Disables database sessions to prevent polluting the sessions table
       (The /api/complete endpoint checks `if db:` before creating sessions)
    3. Bypasses kill switch middleware (it also uses db and would fail with null db)

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

    # Bypass kill switch middleware (since it also uses db and would error with None)
    # This patches is_path_exempt to return True for all paths
    with patch("app.middleware.kill_switch.is_path_exempt", return_value=True):
        yield

    # Clean up
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


class RealAPICallError(Exception):
    """Raised when a test tries to make a real API call without proper mocking."""

    pass


def _raise_real_api_error(*args, **kwargs):
    """Raise error when real API is called without mocking."""
    raise RealAPICallError(
        "Test attempted to make a real LLM API call! "
        "All tests must mock adapter.complete() or adapter.stream(). "
        "Use the mock_claude_adapter or mock_gemini_adapter fixtures, "
        "or patch the adapter in your test."
    )


@pytest.fixture(autouse=True)
def block_real_llm_calls(request):
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
        mock_anthropic.return_value.messages.create = AsyncMock(
            side_effect=_raise_real_api_error
        )
        mock_genai.return_value.aio.models.generate_content = AsyncMock(
            side_effect=_raise_real_api_error
        )
        yield


# Reusable mock fixtures for adapters
@pytest.fixture
def mock_claude_response():
    """Factory for creating mock Claude completion results."""
    from app.adapters.base import CompletionResult

    def _create(
        content: str = "Mocked response",
        model: str = "claude-sonnet-4-5-20250514",
        input_tokens: int = 10,
        output_tokens: int = 5,
    ):
        return CompletionResult(
            content=content,
            model=model,
            provider="claude",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="end_turn",
        )

    return _create


@pytest.fixture
def mock_gemini_response():
    """Factory for creating mock Gemini completion results."""
    from app.adapters.base import CompletionResult

    def _create(
        content: str = "Mocked Gemini response",
        model: str = "gemini-3-flash-preview",
        input_tokens: int = 8,
        output_tokens: int = 4,
    ):
        return CompletionResult(
            content=content,
            model=model,
            provider="gemini",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            finish_reason="STOP",
        )

    return _create
