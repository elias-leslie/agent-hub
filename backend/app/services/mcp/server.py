"""MCP Server - Expose Agent Hub tools via Model Context Protocol.

Enables external AI applications (Claude Code, IDEs, custom agents) to
use Agent Hub's AI capabilities as tools through the MCP standard.
"""

import logging
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from app.adapters.base import Message
from app.constants import DEFAULT_OUTPUT_LIMIT
from app.services.router import ModelRouter

logger = logging.getLogger(__name__)

# Global router instance for tools
_router: ModelRouter | None = None


def _get_router() -> ModelRouter:
    """Get or create the global router instance."""
    global _router
    if _router is None:
        _router = ModelRouter()
    return _router


@asynccontextmanager
async def server_lifespan(server: FastMCP):
    """Initialize resources on server startup."""
    logger.info("MCP Server starting up")
    # Ensure router is initialized
    _get_router()
    try:
        yield {}
    finally:
        logger.info("MCP Server shutting down")


# Create MCP server instance
mcp_server = FastMCP(
    name="agent-hub",
    lifespan=server_lifespan,
)


@mcp_server.tool()
async def complete(
    prompt: str,
    model: str = "claude-sonnet-4-5",
    max_tokens: int = DEFAULT_OUTPUT_LIMIT,
    temperature: float = 1.0,
    ctx: Context[ServerSession, dict[str, Any]] | None = None,
) -> str:
    """
    Generate AI completion using Agent Hub's unified provider system.

    Args:
        prompt: The text prompt to complete
        model: Model to use (claude-sonnet-4-5, claude-opus-4-5, gemini-3-flash-preview)
        max_tokens: Maximum tokens in response
        temperature: Sampling temperature (0.0-2.0)

    Returns:
        Generated text response
    """
    router = _get_router()

    messages = [Message(role="user", content=prompt)]

    if ctx:
        await ctx.info(f"Generating completion with {model}...")

    result = await router.complete(
        messages=messages,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )

    if ctx:
        await ctx.info(f"Completed: {result.input_tokens} in, {result.output_tokens} out")

    return result.content


@mcp_server.tool()
async def chat(
    messages: list[dict[str, str]],
    model: str = "claude-sonnet-4-5",
    system: str | None = None,
    max_tokens: int = DEFAULT_OUTPUT_LIMIT,
    ctx: Context[ServerSession, dict[str, Any]] | None = None,
) -> str:
    """
    Multi-turn chat completion with conversation history.

    Args:
        messages: List of {"role": "user"|"assistant", "content": "text"}
        model: Model to use
        system: Optional system prompt
        max_tokens: Maximum tokens in response

    Returns:
        Assistant's response text
    """
    router = _get_router()

    # Build message list
    msg_list: list[Message] = []
    if system:
        msg_list.append(Message(role="system", content=system))

    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        if role in ("user", "assistant", "system"):
            msg_list.append(Message(role=role, content=content))  # type: ignore[arg-type]

    if ctx:
        await ctx.info(f"Chat completion with {len(msg_list)} messages...")

    result = await router.complete(
        messages=msg_list,
        model=model,
        max_tokens=max_tokens,
    )

    return result.content


@mcp_server.tool()
async def analyze_code(
    code: str,
    language: str = "python",
    analysis_type: str = "review",
    ctx: Context[ServerSession, dict[str, Any]] | None = None,
) -> str:
    """
    Analyze code for issues, improvements, or explanations.

    Args:
        code: Source code to analyze
        language: Programming language (python, javascript, typescript, etc.)
        analysis_type: Type of analysis (review, explain, improve, security)

    Returns:
        Analysis results
    """
    router = _get_router()

    prompts = {
        "review": f"Review this {language} code for quality, bugs, and improvements:\n\n```{language}\n{code}\n```",
        "explain": f"Explain what this {language} code does, step by step:\n\n```{language}\n{code}\n```",
        "improve": f"Suggest improvements for this {language} code:\n\n```{language}\n{code}\n```",
        "security": f"Analyze this {language} code for security vulnerabilities:\n\n```{language}\n{code}\n```",
    }

    prompt = prompts.get(analysis_type, prompts["review"])

    if ctx:
        await ctx.info(f"Analyzing code ({analysis_type})...")

    msg_list = [Message(role="user", content=prompt)]
    result = await router.complete(messages=msg_list, model="claude-sonnet-4-5")

    return result.content


@mcp_server.tool()
async def models() -> list[dict[str, str]]:
    """
    List available AI models.

    Returns:
        List of model info with name, provider, and capabilities
    """
    return [
        {
            "name": "claude-sonnet-4-5",
            "provider": "anthropic",
            "capabilities": "General purpose, balanced cost/quality",
        },
        {
            "name": "claude-opus-4-5",
            "provider": "anthropic",
            "capabilities": "Best reasoning, highest quality",
        },
        {
            "name": "claude-haiku-4-5",
            "provider": "anthropic",
            "capabilities": "Fast, cost-effective",
        },
        {
            "name": "gemini-3-flash-preview",
            "provider": "google",
            "capabilities": "Fast multimodal, good for simple tasks",
        },
        {
            "name": "gemini-3-pro-preview",
            "provider": "google",
            "capabilities": "Better reasoning, complex tasks",
        },
    ]


# ============================================================================
# MCP Resources - Expose data to MCP clients
# ============================================================================


async def _get_active_sessions() -> list[dict[str, Any]]:
    """Query active sessions from database."""
    from sqlalchemy import select

    from app.db import _get_session_factory
    from app.models import Session as DbSession

    factory = _get_session_factory()
    async with factory() as db:
        result = await db.execute(select(DbSession).where(DbSession.status == "active").limit(100))
        sessions = result.scalars().all()
        return [
            {
                "id": str(s.id),
                "project_id": str(s.project_id),
                "provider": str(s.provider),
                "model": str(s.model),
                "status": str(s.status),
            }
            for s in sessions
        ]


@mcp_server.resource(
    "agenthub://sessions",
    name="sessions",
    description="List of active Agent Hub sessions",
)
async def list_sessions_resource() -> str:
    """Return list of active sessions as JSON."""
    import json

    sessions = await _get_active_sessions()
    return json.dumps(sessions, indent=2)


@mcp_server.resource(
    "agenthub://sessions/{session_id}",
    name="session",
    description="Get details for a specific session",
)
async def get_session_resource(session_id: str) -> str:
    """Return session details as JSON."""
    import json

    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.db import _get_session_factory
    from app.models import Session as DbSession

    factory = _get_session_factory()
    async with factory() as db:
        result = await db.execute(
            select(DbSession)
            .options(selectinload(DbSession.messages))
            .where(DbSession.id == session_id)
        )
        session = result.scalar_one_or_none()

        if not session:
            return json.dumps({"error": f"Session {session_id} not found"})

        return json.dumps(
            {
                "id": str(session.id),
                "project_id": str(session.project_id),
                "provider": str(session.provider),
                "model": str(session.model),
                "status": str(session.status),
                "message_count": len(session.messages) if session.messages else 0,
                "created_at": session.created_at.isoformat()
                if session.created_at is not None
                else None,
            }
        )


@mcp_server.resource(
    "agenthub://models",
    name="models",
    description="List of available AI models",
)
async def list_models_resource() -> str:
    """Return available models as JSON."""
    import json

    model_list = await models()
    return json.dumps(model_list, indent=2)


# ============================================================================
# MCP Prompts - Pre-built prompts for common workflows
# ============================================================================


@mcp_server.prompt(
    name="code_review",
    description="Generate a code review request for given code",
)
def code_review_prompt(code: str, language: str = "python") -> list[dict[str, str]]:
    """
    Create a code review prompt.

    Args:
        code: Source code to review
        language: Programming language (default: python)

    Returns:
        List of messages for code review
    """
    return [
        {
            "role": "user",
            "content": f"""Please review the following {language} code for:
- Code quality and best practices
- Potential bugs or issues
- Performance considerations
- Security vulnerabilities
- Suggestions for improvement

```{language}
{code}
```

Provide specific, actionable feedback.""",
        }
    ]


@mcp_server.prompt(
    name="summarize",
    description="Generate a summarization request for given text",
)
def summarize_prompt(text: str, style: str = "concise") -> list[dict[str, str]]:
    """
    Create a summarization prompt.

    Args:
        text: Text to summarize
        style: Summary style (concise, detailed, bullet_points)

    Returns:
        List of messages for summarization
    """
    style_instructions = {
        "concise": "Provide a brief 2-3 sentence summary.",
        "detailed": "Provide a comprehensive summary covering all key points.",
        "bullet_points": "Summarize the key points as a bulleted list.",
    }
    instruction = style_instructions.get(style, style_instructions["concise"])

    return [
        {
            "role": "user",
            "content": f"""Summarize the following text.

{instruction}

Text to summarize:
{text}""",
        }
    ]


@mcp_server.prompt(
    name="translate",
    description="Generate a translation request",
)
def translate_prompt(text: str, target_language: str) -> list[dict[str, str]]:
    """
    Create a translation prompt.

    Args:
        text: Text to translate
        target_language: Target language (e.g., "Spanish", "French", "Japanese")

    Returns:
        List of messages for translation
    """
    return [
        {
            "role": "user",
            "content": f"""Translate the following text to {target_language}.
Preserve the original meaning and tone as much as possible.

Text to translate:
{text}

Provide only the translation without any additional commentary.""",
        }
    ]


class MCPServerManager:
    """Manager for MCP server lifecycle."""

    _instance: "MCPServerManager | None" = None
    _server: FastMCP = mcp_server

    def __new__(cls) -> "MCPServerManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @property
    def server(self) -> FastMCP:
        """Get the MCP server instance."""
        return self._server

    def list_tools(self) -> list[str]:
        """List registered tool names."""
        # FastMCP stores tools in _tool_manager
        if hasattr(self._server, "_tool_manager") and self._server._tool_manager:
            return list(self._server._tool_manager._tools.keys())
        return []

    async def health_check(self) -> dict[str, Any]:
        """Check MCP server health."""
        return {
            "status": "healthy",
            "server_name": self._server.name,
            "tools_count": len(self.list_tools()),
            "tools": self.list_tools(),
        }


def get_mcp_server() -> MCPServerManager:
    """Get the global MCP server manager instance."""
    return MCPServerManager()


def clear_mcp_router() -> None:
    """Clear the global router (for testing)."""
    global _router
    _router = None
