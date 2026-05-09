import os
from pathlib import Path

import httpx
from mcp.server.fastmcp import FastMCP

from app.api.memory_agent_handlers import build_progressive_context_response
from app.config import AGENT_HUB_BACKEND_PORT
from app.services.memory.context_resilience import MemoryFailureDetails
from app.services.memory.failure_reporting import MemoryFailureReport, report_memory_failure
from app.services.memory.service import MemoryScope

# Initialize FastMCP server
mcp = FastMCP("agent-hub")

# Configuration
AGENT_HUB_API = os.getenv("AGENT_HUB_API", f"http://localhost:{AGENT_HUB_BACKEND_PORT}/api")
DEFAULT_TIMEOUT = 30.0


async def _query_progressive_context(query: str, project_id: str | None = None) -> str:
    """Helper to query the centralized progressive-context builder directly."""
    scope = MemoryScope.PROJECT if project_id else MemoryScope.GLOBAL
    response = await build_progressive_context_response(
        query=query,
        scope=scope,
        scope_id=project_id,
        debug=False,
        include_global=True,
        task_type=None,
        project_id=project_id,
    )
    if response.status != "ok" and response.failure is not None:
        await report_memory_failure(
            MemoryFailureReport(
                failure=MemoryFailureDetails(
                    operation=response.failure.operation,
                    attempts=response.failure.attempts,
                    error_type=response.failure.error_type,
                    error_message=response.failure.error_message,
                    latency_ms=response.failure.latency_ms,
                ),
                consumer_profile="mcp_system_instruction",
                project_id=project_id,
                source="mcp_progressive_context",
            )
        )
    return response.formatted


@mcp.resource("memory://context")
async def get_memory_context() -> str:
    """
    Get the progressive memory context for the current task.
    Returns a formatted string containing Mandates, Guardrails, and References.
    """
    query = "current task context"
    return await _query_progressive_context(query)


@mcp.prompt("system_instruction")
async def get_system_instruction() -> str:
    """
    Get the authoritative system instructions (Mandates and Guardrails) for the current session.
    Use this to initialize your context.
    """
    query = "system initialization"
    context = await _query_progressive_context(query)

    default_template = """You are an AI assistant integrated with the Agent-Hub Memory System.
The following are the ACTIVE MANDATES and GUARDRAILS for this environment.
You MUST adhere to these rules strictly.

{context}"""

    from app.services.prompt_service import get_prompt_content

    template = await get_prompt_content("mcp-system-instruction", default_template)
    return template.format(context=context)


@mcp.tool()
async def save_learning(
    content: str, summary: str, tier: str = "reference", confidence: int = 80
) -> str:
    """
    Save a new learning to the agent-hub memory system.

    Args:
        content: The knowledge or instruction to save.
        summary: Short action phrase (~20 chars) for the index (e.g. "use sf-commit").
        tier: The injection tier (mandate, guardrail, reference, archive).
        confidence: Confidence score (0-100).
    """
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        payload = {
            "content": content,
            "summary": summary,
            "injection_tier": tier,
            "confidence": confidence,
        }
        try:
            response = await client.post(f"{AGENT_HUB_API}/memory/save-learning", json=payload)
            response.raise_for_status()
            return f"Successfully saved learning: {summary}"
        except httpx.HTTPStatusError as e:
            # Try to get the detail/hint from the response
            try:
                error_detail = e.response.json()
                if isinstance(error_detail, dict):
                    # Handle FastAPI detail structure
                    detail = error_detail.get("detail", {})
                    if isinstance(detail, dict) and "hint" in detail:
                        return (
                            f"Validation Failed: {detail.get('message')}\n\nHINT:\n{detail['hint']}"
                        )
                    elif isinstance(detail, str):
                        return f"Request Failed: {detail}"
                return f"HTTP Error {e.response.status_code}: {e.response.text}"
            except Exception:
                return f"HTTP Error {e.response.status_code}: {e!s}"
        except Exception as e:
            return f"Error saving learning: {type(e).__name__}: {e}"


@mcp.tool()
async def search_memory(query: str, limit: int = 5) -> str:
    """
    Search the agent-hub memory system for specific information.
    """
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        params = {"query": query, "limit": limit}
        try:
            response = await client.get(f"{AGENT_HUB_API}/memory/search", params=params)
            response.raise_for_status()
            results = response.json()
            # Format results simply
            formatted = []
            if not results.get("results"):
                return "No results found."

            for item in results.get("results", []):
                content = item.get("content", "")
                score = item.get("score", 0)
                formatted.append(f"- [{score:.2f}] {content}")
            return "\n".join(formatted)
        except Exception as e:
            return f"Error searching memory: {e!s}"


def sync_gemini_context():
    """Syncs the GEMINI.md context file on server startup."""
    import subprocess

    script_path = str(Path(__file__).resolve().parent.parent / "scripts" / "update_gemini_context.sh")
    try:
        # Run the sync script
        result = subprocess.run([script_path], capture_output=True, text=True)
        if result.returncode != 0:
            print(f"Failed to sync context: {result.stderr}")
    except Exception as e:
        print(f"Error running sync script: {e}")


if __name__ == "__main__":
    # Magic Hook: Sync context immediately when Antigravity starts this server
    sync_gemini_context()
    mcp.run()
