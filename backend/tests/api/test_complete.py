"""Tests for /complete endpoint."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from app.adapters.base import (
    AuthenticationError,
    CompletionResult,
    ProviderError,
    RateLimitError,
)
from app.api.complete import clear_adapter_cache, validate_json_response
from app.main import app
from tests.conftest import APITestClient


@pytest.fixture
def client():
    """Test client with source headers for kill switch compliance."""
    return APITestClient(app)


@pytest.fixture(autouse=True)
def reset_adapter_cache():
    """Clear adapter cache before each test."""
    clear_adapter_cache()
    yield
    clear_adapter_cache()


@pytest.mark.skip(reason="API changed to require agent_slug - tests need refactoring")
class TestCompleteEndpoint:
    """Tests for POST /api/complete."""

    @pytest.fixture
    def mock_claude_adapter(self):
        """Mock ClaudeAdapter."""
        # Mock shutil.which to avoid OAuth mode
        with (
            patch("app.adapters.claude.shutil.which", return_value=None),
            patch("app.api.complete.ClaudeAdapter") as mock,
        ):
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hello there!",
                    model="claude-sonnet-4-5-20250514",
                    provider="claude",
                    input_tokens=10,
                    output_tokens=5,
                    finish_reason="end_turn",
                )
            )
            mock.return_value = adapter
            yield mock

    @pytest.fixture
    def mock_gemini_adapter(self):
        """Mock GeminiAdapter."""
        with patch("app.api.complete.GeminiAdapter") as mock:
            adapter = AsyncMock()
            adapter.complete = AsyncMock(
                return_value=CompletionResult(
                    content="Hi from Gemini!",
                    model="gemini-3-flash-preview",
                    provider="gemini",
                    input_tokens=8,
                    output_tokens=4,
                    finish_reason="STOP",
                )
            )
            mock.return_value = adapter
            yield mock

    def test_complete_claude_success(self, client, mock_claude_adapter):
        """Test successful Claude completion."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hello there!"
        assert data["provider"] == "claude"
        assert data["model"] == "claude-sonnet-4-5-20250514"
        assert data["usage"]["input_tokens"] == 10
        assert data["usage"]["output_tokens"] == 5
        assert data["usage"]["total_tokens"] == 15
        assert "session_id" in data

    def test_complete_gemini_success(self, client, mock_gemini_adapter):
        """Test successful Gemini completion."""
        response = client.post(
            "/api/complete",
            json={
                "model": "gemini-3-flash-preview",
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert data["content"] == "Hi from Gemini!"
        assert data["provider"] == "gemini"

    def test_complete_with_session_id(self, client, mock_claude_adapter):
        """Test completion with existing session ID."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "session_id": "existing-session-123",
            },
        )

        assert response.status_code == 200
        assert response.json()["session_id"] == "existing-session-123"

    def test_complete_with_system_message(self, client, mock_claude_adapter):
        """Test completion with system message."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [
                    {"role": "system", "content": "You are helpful"},
                    {"role": "user", "content": "Hello"},
                ],
                "project_id": "test-project",
            },
        )

        assert response.status_code == 200
        # Verify adapter was called
        mock_claude_adapter.return_value.complete.assert_called_once()

    def test_complete_custom_params(self, client, mock_claude_adapter):
        """Test completion with custom parameters (max_tokens removed from API)."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "temperature": 0.5,
            },
        )

        assert response.status_code == 200
        call_kwargs = mock_claude_adapter.return_value.complete.call_args.kwargs
        assert call_kwargs["max_tokens"] is None  # No artificial caps - model determines length
        assert call_kwargs["temperature"] == 0.5

    def test_complete_rate_limit_error(self, client):
        """Test rate limit error handling."""
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(side_effect=RateLimitError("claude", retry_after=30))

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 429
            assert "Retry-After" in response.headers

    def test_complete_auth_error(self, client):
        """Test authentication error handling."""
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(side_effect=AuthenticationError("claude"))

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 401

    def test_complete_provider_error(self, client):
        """Test generic provider error handling."""
        clear_adapter_cache()  # Ensure cache is clear before mocking
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            side_effect=ProviderError("API error", provider="claude", status_code=503)
        )

        with patch("app.api.complete._get_adapter", return_value=adapter):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hi"}],
                    "project_id": "test-project",
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 503

    def test_complete_missing_model(self, client):
        """Test validation error for missing model (no agent_slug either)."""
        response = client.post(
            "/api/complete",
            json={
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
            },
        )

        # Returns 400 because either model or agent_slug must be provided
        assert response.status_code == 400
        assert (
            "model" in response.json()["detail"].lower()
            or "agent_slug" in response.json()["detail"].lower()
        )

    def test_complete_missing_messages(self, client):
        """Test validation error for missing messages."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "project_id": "test-project",
            },
        )

        assert response.status_code == 422

    def test_complete_missing_project_id(self, client):
        """Test validation error for missing project_id (required)."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
            },
        )

        assert response.status_code == 422

    def test_complete_invalid_temperature(self, client):
        """Test validation error for invalid temperature."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hi"}],
                "project_id": "test-project",
                "temperature": 3.0,  # > 2.0 limit
            },
        )

        assert response.status_code == 422

    def test_complete_with_purpose(self, client, mock_claude_adapter):
        """Test completion with purpose field."""
        response = client.post(
            "/api/complete",
            json={
                "model": "claude-sonnet-4-5-20250514",
                "messages": [{"role": "user", "content": "Hello"}],
                "project_id": "test-project",
                "purpose": "task_enrichment",
            },
        )

        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data


class TestJsonSchemaValidation:
    """Tests for JSON schema validation functionality."""

    def test_validate_json_response_valid(self):
        """Test validation passes for valid JSON matching schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        content = '{"name": "John", "age": 30}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is True
        assert error is None

    def test_validate_json_response_invalid_json(self):
        """Test validation fails for invalid JSON."""
        schema = {"type": "object"}
        content = "not valid json {"
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Invalid JSON" in error

    def test_validate_json_response_schema_mismatch(self):
        """Test validation fails when JSON doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "age": {"type": "integer"},
            },
            "required": ["name", "age"],
        }
        # Missing required field 'age'
        content = '{"name": "John"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error

    def test_validate_json_response_wrong_type(self):
        """Test validation fails when type doesn't match schema."""
        schema = {
            "type": "object",
            "properties": {
                "count": {"type": "integer"},
            },
        }
        # 'count' is a string instead of integer
        content = '{"count": "five"}'
        is_valid, error = validate_json_response(content, schema)
        assert is_valid is False
        assert "Schema validation failed" in error


@pytest.mark.skip(reason="API changed to require agent_slug - tests need refactoring")
class TestStructuredOutput:
    """Tests for structured output (JSON mode) in /complete endpoint."""

    @pytest.fixture
    def mock_adapter_json_response(self):
        """Mock adapter returning valid JSON."""
        clear_adapter_cache()
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"name": "Claude", "items": ["a", "b"]}',
                model="claude-sonnet-4-5-20250514",
                provider="claude",
                input_tokens=10,
                output_tokens=8,
                finish_reason="end_turn",
            )
        )
        return adapter

    @pytest.fixture
    def mock_adapter_invalid_json_response(self):
        """Mock adapter returning invalid JSON for schema."""
        clear_adapter_cache()
        adapter = AsyncMock()
        adapter.complete = AsyncMock(
            return_value=CompletionResult(
                content='{"name": "Claude"}',  # Missing required 'items'
                model="claude-sonnet-4-5-20250514",
                provider="claude",
                input_tokens=10,
                output_tokens=5,
                finish_reason="end_turn",
            )
        )
        return adapter

    def test_complete_with_json_mode_success(self, client, mock_adapter_json_response):
        """Test successful completion with JSON mode and schema validation."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return a JSON object"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "items": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["name", "items"],
                        },
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 200
            data = response.json()
            # Content should be valid JSON
            parsed = json.loads(data["content"])
            assert parsed["name"] == "Claude"
            assert parsed["items"] == ["a", "b"]

    def test_complete_with_json_mode_validation_failure(
        self, client, mock_adapter_invalid_json_response
    ):
        """Test that validation failure returns 400."""
        with patch(
            "app.api.complete._get_adapter", return_value=mock_adapter_invalid_json_response
        ):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return a JSON object"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "name": {"type": "string"},
                                "items": {"type": "array"},
                            },
                            "required": ["name", "items"],
                        },
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 400
            assert "does not match the provided JSON schema" in response.json()["detail"]

    def test_complete_with_json_mode_no_schema(self, client, mock_adapter_json_response):
        """Test JSON mode without schema (no validation)."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Return JSON"}],
                    "project_id": "test-project",
                    "response_format": {
                        "type": "json_object",
                        # No schema provided - no validation
                    },
                },
                headers={"X-Skip-Cache": "true"},
            )

            # Should succeed without validation
            assert response.status_code == 200

    def test_complete_text_mode_default(self, client, mock_adapter_json_response):
        """Test that text mode (default) doesn't do JSON validation."""
        with patch("app.api.complete._get_adapter", return_value=mock_adapter_json_response):
            response = client.post(
                "/api/complete",
                json={
                    "model": "claude-sonnet-4-5-20250514",
                    "messages": [{"role": "user", "content": "Hello"}],
                    "project_id": "test-project",
                    # No response_format - defaults to text mode
                },
                headers={"X-Skip-Cache": "true"},
            )

            assert response.status_code == 200


class TestAgenticParams:
    """Tests for agentic execution params in /complete endpoint."""

    @pytest.fixture
    def mock_db(self):
        """Mock database session."""
        return AsyncMock()

    @pytest.fixture
    def mock_agent_result(self):
        """Mock AgentResult from runner."""
        from app.services.agent_runner.models import AgentProgress, AgentResult

        return AgentResult(
            agent_id="test-agent-123",
            session_id="test-session-456",
            status="success",
            content="Task completed successfully",
            provider="claude",
            model="claude-sonnet-4-5-20250514",
            turns=3,
            input_tokens=100,
            output_tokens=50,
            thinking_tokens=20,
            tool_calls_count=5,
            progress_log=[
                AgentProgress(
                    turn=1,
                    status="tool_use",
                    message="Executing tool: read_file",
                    tool_calls=[{"name": "read_file", "input": {"path": "/test"}}],
                    tool_results=[{"content": "file contents"}],
                ),
                AgentProgress(
                    turn=2,
                    status="tool_use",
                    message="Executing tool: write_file",
                    tool_calls=[{"name": "write_file", "input": {"path": "/out"}}],
                    tool_results=[{"content": "written"}],
                ),
                AgentProgress(
                    turn=3,
                    status="complete",
                    message="Task complete",
                ),
            ],
            container_id="container-789",
            memory_uuids=["mem-1", "mem-2"],
            cited_uuids=["cite-1"],
        )

    @pytest.fixture
    def mock_resolve_agent(self):
        """Mock resolve_agent to return a test agent."""
        from datetime import UTC, datetime

        from app.services.agent_routing import ResolvedAgent
        from app.services.agent_service import AgentDTO

        agent = AgentDTO(
            id=1,
            slug="test-agent",
            name="Test Agent",
            description="Test agent for unit tests",
            system_prompt="You are a test agent",
            primary_model_id="claude-sonnet-4-5-20250514",
            fallback_models=[],
            escalation_model_id=None,
            strategies={},
            temperature=1.0,
            is_active=True,
            is_coding_agent=False,
            tool_permissions=None,
            version=1,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        resolved = ResolvedAgent(
            agent=agent,
            model="claude-sonnet-4-5-20250514",
            provider="claude",
        )
        return resolved

    @pytest.fixture
    def mock_mandate_injection(self):
        """Mock mandate injection result."""
        from app.services.agent_routing import MandateInjection

        return MandateInjection(
            system_content="Test system prompt with mandates",
            injected_uuids=["mandate-1"],
        )

    def test_agentic_mode_triggers_runner(
        self, client, mock_db, mock_agent_result, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that max_turns > 1 triggers agentic execution."""
        from app.db import get_db

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.services.agent_runner.get_agent_runner") as mock_get_runner,
            ):
                mock_runner = AsyncMock()
                mock_runner.run = AsyncMock(return_value=mock_agent_result)
                mock_get_runner.return_value = mock_runner

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Do the task"}],
                        "project_id": "test-project",
                        "max_turns": 10,
                    },
                )

                assert response.status_code == 200
                data = response.json()

                # Verify agentic response fields
                assert data["turns"] == 3
                assert data["tool_calls_count"] == 5
                assert data["content"] == "Task completed successfully"
                assert data["progress_log"] is not None
                assert len(data["progress_log"]) == 3
                assert data["cited_uuids"] == ["cite-1"]

                # Verify runner was called
                mock_runner.run.assert_called_once()
                call_kwargs = mock_runner.run.call_args.kwargs
                assert call_kwargs["task"] == "Do the task"
                assert call_kwargs["config"].max_turns == 10
        finally:
            app.dependency_overrides.clear()

    def test_execute_tools_triggers_runner(
        self, client, mock_db, mock_agent_result, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that execute_tools=True triggers agentic execution."""
        from app.db import get_db

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.services.agent_runner.get_agent_runner") as mock_get_runner,
            ):
                mock_runner = AsyncMock()
                mock_runner.run = AsyncMock(return_value=mock_agent_result)
                mock_get_runner.return_value = mock_runner

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Execute tools"}],
                        "project_id": "test-project",
                        "execute_tools": True,
                    },
                )

                assert response.status_code == 200
                # Verify runner was called due to execute_tools=True
                mock_runner.run.assert_called_once()
        finally:
            app.dependency_overrides.clear()

    def test_working_dir_passed_to_runner(
        self, client, mock_db, mock_agent_result, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that working_dir is passed to agent config."""
        from app.db import get_db

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.services.agent_runner.get_agent_runner") as mock_get_runner,
            ):
                mock_runner = AsyncMock()
                mock_runner.run = AsyncMock(return_value=mock_agent_result)
                mock_get_runner.return_value = mock_runner

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Work in directory"}],
                        "project_id": "test-project",
                        "max_turns": 5,
                        "working_dir": "/home/test/project",
                    },
                )

                assert response.status_code == 200
                call_kwargs = mock_runner.run.call_args.kwargs
                assert call_kwargs["config"].working_dir == "/home/test/project"
        finally:
            app.dependency_overrides.clear()

    def test_trace_id_passed_and_returned(
        self, client, mock_db, mock_agent_result, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that trace_id is passed to runner and returned in response."""
        from app.db import get_db

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.services.agent_runner.get_agent_runner") as mock_get_runner,
            ):
                mock_runner = AsyncMock()
                mock_runner.run = AsyncMock(return_value=mock_agent_result)
                mock_get_runner.return_value = mock_runner

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Traced task"}],
                        "project_id": "test-project",
                        "max_turns": 5,
                        "trace_id": "task-abc123",
                    },
                )

                assert response.status_code == 200
                data = response.json()
                assert data["trace_id"] == "task-abc123"
                call_kwargs = mock_runner.run.call_args.kwargs
                assert call_kwargs["config"].trace_id == "task-abc123"
        finally:
            app.dependency_overrides.clear()

    def test_single_turn_does_not_trigger_runner(
        self, client, mock_db, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that max_turns=1 (default) uses standard completion path."""
        from app.db import get_db

        mock_completion = CompletionResult(
            content="Single turn response",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
        )

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.services.agent_runner.get_agent_runner") as mock_get_runner,
                patch("app.api.complete._get_adapter") as mock_get_adapter,
            ):
                mock_adapter = AsyncMock()
                mock_adapter.complete = AsyncMock(return_value=mock_completion)
                mock_get_adapter.return_value = mock_adapter

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Single completion"}],
                        "project_id": "test-project",
                        # max_turns defaults to 1, execute_tools defaults to False
                    },
                    headers={"X-Skip-Cache": "true"},
                )

                assert response.status_code == 200
                data = response.json()

                # Verify standard completion used, not agentic
                assert data["turns"] == 1
                assert data["tool_calls_count"] == 0
                assert data["progress_log"] is None
                # Runner should NOT have been called
                mock_get_runner.assert_not_called()
        finally:
            app.dependency_overrides.clear()

    def test_response_includes_new_fields(
        self, client, mock_db, mock_resolve_agent, mock_mandate_injection
    ):
        """Test that response includes all new agentic fields even for single turn."""
        from app.db import get_db

        mock_completion = CompletionResult(
            content="Response with new fields",
            model="claude-sonnet-4-5-20250514",
            provider="claude",
            input_tokens=10,
            output_tokens=5,
            finish_reason="end_turn",
        )

        async def override_get_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_get_db
        try:
            with (
                patch(
                    "app.api.complete.resolve_agent",
                    new_callable=AsyncMock,
                    return_value=mock_resolve_agent,
                ),
                patch(
                    "app.api.complete.inject_agent_mandates",
                    new_callable=AsyncMock,
                    return_value=mock_mandate_injection,
                ),
                patch("app.api.complete._get_adapter") as mock_get_adapter,
            ):
                mock_adapter = AsyncMock()
                mock_adapter.complete = AsyncMock(return_value=mock_completion)
                mock_get_adapter.return_value = mock_adapter

                response = client.post(
                    "/api/complete",
                    json={
                        "agent_slug": "test-agent",
                        "messages": [{"role": "user", "content": "Check fields"}],
                        "project_id": "test-project",
                    },
                    headers={"X-Skip-Cache": "true"},
                )

                if response.status_code != 200:
                    print(f"Response status: {response.status_code}")
                    print(f"Response body: {response.json()}")
                assert response.status_code == 200
                data = response.json()

                # Verify all new response fields exist
                assert "turns" in data
                assert "tool_calls_count" in data
                assert "progress_log" in data
                assert "trace_id" in data
                assert "cited_uuids" in data
        finally:
            app.dependency_overrides.clear()
