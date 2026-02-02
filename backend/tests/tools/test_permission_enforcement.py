"""Tests for permission enforcement in tool execution."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.tools.base import ToolCall, ToolDecision, ToolResult
from app.services.tools.direct_executor import DirectToolHandler, create_direct_handler
from app.services.tools.permissions import PermissionChecker, PermissionConfig


class TestDirectToolHandlerWithPermissions:
    """Tests for DirectToolHandler permission checking."""

    @pytest.fixture
    def yolo_handler(self) -> DirectToolHandler:
        """Create handler with YOLO permissions (allow all)."""
        config = PermissionConfig.yolo()
        checker = PermissionChecker(config)
        return DirectToolHandler(
            working_dir="/tmp",
            pre_hook=checker.create_hook(),
        )

    @pytest.fixture
    def granular_handler(self) -> DirectToolHandler:
        """Create handler with granular permissions."""
        config = PermissionConfig.granular(
            allow=["read_file"],
            deny=["bash"],
        )
        checker = PermissionChecker(config)
        return DirectToolHandler(
            working_dir="/tmp",
            pre_hook=checker.create_hook(),
        )

    @pytest.mark.asyncio
    async def test_yolo_allows_all_tools(self, yolo_handler: DirectToolHandler) -> None:
        """Test YOLO mode allows all tool calls."""
        tool_call = ToolCall(id="test-1", name="bash", input={"command": "echo hello"})

        decision = await yolo_handler.check_permission(tool_call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_granular_allows_whitelisted(self, granular_handler: DirectToolHandler) -> None:
        """Test granular mode allows whitelisted tools."""
        tool_call = ToolCall(id="test-1", name="read_file", input={"path": "/tmp/test"})

        decision = await granular_handler.check_permission(tool_call)

        assert decision == ToolDecision.ALLOW

    @pytest.mark.asyncio
    async def test_granular_denies_blacklisted(self, granular_handler: DirectToolHandler) -> None:
        """Test granular mode denies blacklisted tools."""
        tool_call = ToolCall(id="test-1", name="bash", input={"command": "rm -rf /"})

        decision = await granular_handler.check_permission(tool_call)

        assert decision == ToolDecision.DENY

    @pytest.mark.asyncio
    async def test_granular_asks_for_unknown(self, granular_handler: DirectToolHandler) -> None:
        """Test granular mode asks for unknown tools."""
        tool_call = ToolCall(id="test-1", name="write_file", input={"path": "/tmp/x"})

        decision = await granular_handler.check_permission(tool_call)

        # write_file is not in allow or deny list, so it should ASK
        assert decision == ToolDecision.ASK


class TestCreateDirectHandlerWithPermissions:
    """Tests for create_direct_handler with permission config."""

    def test_creates_handler_without_permissions(self) -> None:
        """Test creating handler without permissions."""
        handler = create_direct_handler(working_dir="/tmp")

        assert handler is not None
        assert handler._pre_hook is None

    def test_creates_handler_with_yolo_permissions(self) -> None:
        """Test creating handler with YOLO permissions."""
        config = PermissionConfig.yolo().to_dict()
        handler = create_direct_handler(working_dir="/tmp", permission_config=config)

        assert handler is not None
        assert handler._pre_hook is not None

    def test_creates_handler_with_granular_permissions(self) -> None:
        """Test creating handler with granular permissions."""
        config = PermissionConfig.granular(
            allow=["read_file", "bash"],
            deny=["write_file"],
        ).to_dict()
        handler = create_direct_handler(working_dir="/tmp", permission_config=config)

        assert handler is not None
        assert handler._pre_hook is not None

    @pytest.mark.asyncio
    async def test_handler_enforces_permissions(self) -> None:
        """Test that created handler enforces permissions."""
        config = PermissionConfig.granular(
            allow=[],
            deny=["bash"],
        ).to_dict()
        handler = create_direct_handler(working_dir="/tmp", permission_config=config)

        tool_call = ToolCall(id="test-1", name="bash", input={"command": "whoami"})
        decision = await handler.check_permission(tool_call)

        assert decision == ToolDecision.DENY


class TestExecuteToolsGeminiPermissions:
    """Tests for permission enforcement in execute_tools_gemini."""

    @pytest.fixture
    def mock_handler(self) -> MagicMock:
        """Create a mock handler for testing."""
        handler = MagicMock()
        handler.check_permission = AsyncMock()
        handler.execute = AsyncMock()
        return handler

    @pytest.mark.asyncio
    async def test_execute_respects_deny_decision(self, mock_handler: MagicMock) -> None:
        """Test that DENY decision prevents tool execution."""
        from app.services.agent_runner.executor_utils import execute_tools_gemini
        from app.services.agent_runner.models import AgentResult

        mock_handler.check_permission.return_value = ToolDecision.DENY

        result = AgentResult(
            agent_id="test",
            status="running",
            content="",
            provider="gemini",
            model="test-model",
            turns=1,
            input_tokens=0,
            output_tokens=0,
        )

        tool_calls = [MagicMock(id="tc-1", name="bash", input={"command": "whoami"})]
        results = await execute_tools_gemini(
            tool_calls,
            mock_handler,
            result,
            turn=1,
            progress_callback=None,
            log_tool_call_fn=lambda *args: None,
            log_tool_result_fn=lambda *args: None,
        )

        assert len(results) == 1
        assert results[0].is_error is True
        assert "Permission denied" in results[0].content
        mock_handler.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_respects_ask_decision(self, mock_handler: MagicMock) -> None:
        """Test that ASK decision (no user) prevents tool execution."""
        from app.services.agent_runner.executor_utils import execute_tools_gemini
        from app.services.agent_runner.models import AgentResult

        mock_handler.check_permission.return_value = ToolDecision.ASK

        result = AgentResult(
            agent_id="test",
            status="running",
            content="",
            provider="gemini",
            model="test-model",
            turns=1,
            input_tokens=0,
            output_tokens=0,
        )

        tool_calls = [MagicMock(id="tc-1", name="bash", input={"command": "whoami"})]
        results = await execute_tools_gemini(
            tool_calls,
            mock_handler,
            result,
            turn=1,
            progress_callback=None,
            log_tool_call_fn=lambda *args: None,
            log_tool_result_fn=lambda *args: None,
        )

        assert len(results) == 1
        assert results[0].is_error is True
        assert "requires confirmation" in results[0].content
        mock_handler.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_allows_allowed_tools(self, mock_handler: MagicMock) -> None:
        """Test that ALLOW decision permits tool execution."""
        from app.services.agent_runner.executor_utils import execute_tools_gemini
        from app.services.agent_runner.models import AgentResult

        mock_handler.check_permission.return_value = ToolDecision.ALLOW
        mock_handler.execute.return_value = ToolResult(
            tool_use_id="tc-1",
            content="success",
            is_error=False,
        )

        result = AgentResult(
            agent_id="test",
            status="running",
            content="",
            provider="gemini",
            model="test-model",
            turns=1,
            input_tokens=0,
            output_tokens=0,
        )

        tool_calls = [MagicMock(id="tc-1", name="read_file", input={"path": "/tmp/x"})]
        results = await execute_tools_gemini(
            tool_calls,
            mock_handler,
            result,
            turn=1,
            progress_callback=None,
            log_tool_call_fn=lambda *args: None,
            log_tool_result_fn=lambda *args: None,
        )

        assert len(results) == 1
        assert results[0].is_error is False
        assert results[0].content == "success"
        mock_handler.execute.assert_called_once()
