import os

import httpx
from mcp.server.fastmcp import FastMCP

from app.config import AGENT_HUB_BACKEND_PORT
from app.db import async_session
from app.services.memory.context_resilience import MemoryFailureDetails
from app.services.memory.failure_reporting import MemoryFailureReport, report_memory_failure
from app.services.runtime_context import (
    CanonicalContextDeliveryRequest,
    CanonicalContextDeliveryResponse,
    build_canonical_context_delivery,
)

# Initialize FastMCP server
mcp = FastMCP("agent-hub")

# Configuration
AGENT_HUB_API = os.getenv("AGENT_HUB_API", f"http://localhost:{AGENT_HUB_BACKEND_PORT}/api")
DEFAULT_TIMEOUT = 30.0


async def _get_canonical_context_delivery(
    query: str,
    project_id: str | None = None,
    session_id: str | None = None,
    workflow_ids: list[str] | None = None,
    requested_source_ids: list[str] | None = None,
) -> CanonicalContextDeliveryResponse:
    """Build the same versioned delivery used by every other context surface."""
    async with async_session() as db:
        return await build_canonical_context_delivery(
            db,
            CanonicalContextDeliveryRequest(
                consumer_surface="mcp",
                consumer_profile="agent_startup",
                project_id=project_id,
                session_id=session_id,
                workflow_ids=workflow_ids or [],
                requested_source_ids=requested_source_ids or [],
                task=query,
                query=query,
            ),
        )


async def _query_progressive_context(query: str, project_id: str | None = None) -> str:
    """Compatibility string projection of the canonical MCP delivery."""
    delivery = await _get_canonical_context_delivery(query, project_id)
    if delivery.status != "ok" and delivery.failure is not None:
        await report_memory_failure(
            MemoryFailureReport(
                failure=MemoryFailureDetails(
                    operation=delivery.failure.operation,
                    attempts=1,
                    error_type=delivery.failure.error_type,
                    error_message=delivery.failure.error_message,
                    latency_ms=0,
                ),
                consumer_profile="mcp_system_instruction",
                project_id=project_id,
                source="mcp_canonical_context",
            )
        )
    return delivery.rendered


@mcp.tool()
async def retrieve_context(query: str, project_id: str | None = None, session_id: str | None = None,
                           workflow_ids: list[str] | None = None, requested_source_ids: list[str] | None = None) -> dict:
    """Retrieve applicable canonical context; activate workflows only at the user's explicit request.

    Pass source IDs from the on-demand index to retrieve full source text. Native
    instructions are preserved; this response is retrieval, not observed injection.
    """
    result = await _get_canonical_context_delivery(query, project_id, session_id, workflow_ids, requested_source_ids)
    return result.model_dump(mode="json")


@mcp.resource("memory://context")
async def get_memory_context() -> str:
    """
    Get the progressive memory context for the current task.
    Returns a formatted string containing Mandates, Guardrails, and References.
    """
    query = "current task context"
    return await _query_progressive_context(query)


@mcp.tool()
async def context_maintenance(request: dict | None = None) -> dict:
    """Inspect or act on the canonical maintenance queue using MaintenanceRequest.

Omit request to retrieve the exact action schema on demand.
Use action=list with context={consumer_surface:'mcp', project_id, session_id}.
Inspect exact evidence and claim before work. Routine work is handled by the
scheduled curator; raise only necessary decisions with a recommendation.
Reported owner answers must quote a real conversation, never an inference.
Use action=inspect for evidence, acknowledge with exact item versions after
reading, and release claims at handoff. No source changes follow from a label.
"""
    from app.services.context_maintenance_actions import MaintenanceRequest, handle_maintenance
    if request is None:
        return {"schema": MaintenanceRequest.model_json_schema()}
    parsed = MaintenanceRequest.model_validate(request)
    async with async_session() as db:
        if parsed.action in {"review", "reconcile", "repair", "apply", "resolve", "dismiss"}:
            from app.services.credential_manager import get_credential_manager
            await get_credential_manager().load(db)
        return await handle_maintenance(db, parsed, "agent:mcp")


@mcp.prompt("system_instruction")
async def get_system_instruction() -> str:
    """
    Get the authoritative system instructions (Mandates and Guardrails) for the current session.
    Use this to initialize your context.
    """
    return await _query_progressive_context("system initialization")


@mcp.tool()
async def record_context_feedback(source_type: str, source_id: str, source_revision: str,
                                  session_id: str, turn_id: str, assessment: str, evidence: str) -> dict:
    """Optionally record an attributed agent assessment, without inline chat markers.

    Do not infer usefulness from a citation, claim hidden prompt visibility, or
    label an agent assessment as a user rating. No source is modified.
    """
    from app.services.context_governance import ContextFeedback, record_feedback
    request = ContextFeedback(source_type=source_type, source_id=source_id, source_revision=source_revision,
                              session_id=session_id, turn_id=turn_id, assessment=assessment,
                              actor_type="agent", evidence=evidence)
    async with async_session() as db:
        return await record_feedback(db, request, "agent:mcp")


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


if __name__ == "__main__":
    mcp.run()
