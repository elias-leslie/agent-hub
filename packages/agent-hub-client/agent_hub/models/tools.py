"""Tool-related models for Agent Hub client."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Tool definition for model to call."""

    name: str = Field(..., description="Tool name")
    description: str = Field(..., description="Tool description")
    input_schema: dict[str, Any] = Field(
        ..., description="JSON Schema for tool parameters"
    )
    allowed_callers: list[str] = Field(
        default_factory=lambda: ["direct"],
        description="Who can call this tool: direct, code_execution_20250825",
    )


class ToolCall(BaseModel):
    """A tool call requested by the model."""

    id: str = Field(..., description="Unique ID for this tool call")
    name: str = Field(..., description="Tool name")
    input: dict[str, Any] = Field(..., description="Tool input parameters")
    caller_type: str = Field(
        default="direct", description="Who initiated: direct or code_execution"
    )
    caller_tool_id: str | None = Field(
        default=None, description="Tool ID if called from code execution"
    )


class ToolResultMessage(BaseModel):
    """Tool result message to send back to the model."""

    role: Literal["user"] = "user"
    content: list[dict[str, Any]] = Field(..., description="Tool result content blocks")

    @classmethod
    def from_result(
        cls,
        tool_use_id: str,
        result: str,
        is_error: bool = False,
    ) -> "ToolResultMessage":
        """Create a tool result message from execution result.

        Args:
            tool_use_id: The tool call ID this result corresponds to.
            result: The tool execution result (or error message).
            is_error: Whether this is an error result.

        Returns:
            ToolResultMessage ready to send to the API.
        """
        return cls(
            content=[
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result,
                    **({"is_error": True} if is_error else {}),
                }
            ]
        )
