import os

import httpx
from mcp.server.fastmcp import FastMCP

# Initialize FastMCP server
mcp = FastMCP("agent-hub")

# Configuration
AGENT_HUB_API = os.getenv("AGENT_HUB_API", "http://localhost:8003/api")
DEFAULT_TIMEOUT = 30.0


async def _query_progressive_context(query: str, project_id: str | None = None) -> str:
    """Helper to query the agent-hub progressive context endpoint."""
    async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
        params = {"query": query}
        if project_id:
            # If we have a project ID, let's assume we want project scope which includes global
            params["x_scope_id"] = project_id
            params["x_memory_scope"] = "project"
            params["include_global"] = "true"
        else:
            params["x_memory_scope"] = "global"

        try:
            response = await client.get(
                f"{AGENT_HUB_API}/memory/progressive-context", params=params
            )
            response.raise_for_status()
            data = response.json()
            return data.get("formatted", "")
        except Exception as e:
            return f"Error fetching context: {type(e).__name__}: {e}"


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
    return f"""
You are an AI assistant integrated with the Agent-Hub Memory System.
The following are the ACTIVE MANDATES and GUARDRAILS for this environment.
You MUST adhere to these rules strictly.

{context}
"""


@mcp.tool()
async def save_learning(
    content: str, summary: str, tier: str = "reference", confidence: int = 80
) -> str:
    """
    Save a new learning to the agent-hub memory system.

    Args:
        content: The knowledge or instruction to save.
        summary: Short action phrase (~20 chars) for the index (e.g. "use sf-commit").
        tier: The injection tier (mandate, guardrail, reference).
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

    script_path = "/home/kasadis/agent-hub/scripts/update_gemini_context.sh"
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
