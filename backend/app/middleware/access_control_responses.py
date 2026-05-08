"""Error response builders for access control middleware."""

from typing import Any

from starlette.responses import JSONResponse


def missing_headers_response(missing_headers: list[str]) -> JSONResponse:
    """Return 400 response for missing required headers."""
    return JSONResponse(
        status_code=400,
        content={
            "error": "missing_required_headers",
            "message": f"Required headers missing: {', '.join(missing_headers)}",
            "required_headers": missing_headers,
            "agent_instructions": {
                "severity": "MANDATORY",
                "action": "STOP - Do not attempt to call this API without proper identification.",
                "guidance": "All Agent Hub API calls require X-Client-Id and X-Request-Source headers. Register a client via the Agent Hub dashboard or use the proper CLI tools (st complete for one-shot, st agent for tool-loop runs) which handle identification.",
                "reason": "This access control exists to track and attribute resource usage.",
            },
        },
    )


def client_not_found_response() -> JSONResponse:
    """Return 403 response for unrecognized client ID."""
    return JSONResponse(
        status_code=403,
        content={
            "error": "client_not_found",
            "message": "Client not found — register via the Agent Hub dashboard",
            "agent_instructions": {
                "severity": "MANDATORY",
                "action": "STOP - Do not attempt to bypass or work around this restriction.",
                "guidance": "The provided X-Client-Id is not registered. Ask the user to register a client via the Agent Hub dashboard.",
                "reason": "This access control exists to track and attribute resource usage.",
            },
        },
    )


def client_suspended_response(client_data: dict[str, Any]) -> JSONResponse:
    """Return 403 response for suspended client."""
    return JSONResponse(
        status_code=403,
        content={
            "error": "client_suspended",
            "message": f"Client '{client_data['display_name']}' is suspended",
            "reason": client_data["suspension_reason"],
            "suspended_at": client_data["suspended_at"].isoformat()
            if client_data["suspended_at"]
            else None,
            "agent_instructions": {
                "severity": "MANDATORY",
                "action": "STOP - Do not attempt to bypass or work around this restriction.",
                "guidance": "This client has been suspended by an administrator. Ask the user to contact admin to restore access or use a different client.",
                "reason": "This access control exists to prevent unauthorized resource usage.",
            },
        },
    )


def client_blocked_response(client_data: dict[str, Any]) -> JSONResponse:
    """Return 403 response for blocked client."""
    return JSONResponse(
        status_code=403,
        content={
            "error": "client_blocked",
            "message": f"Client '{client_data['display_name']}' is permanently blocked",
            "reason": client_data["suspension_reason"],
            "blocked_at": client_data["suspended_at"].isoformat()
            if client_data["suspended_at"]
            else None,
            "agent_instructions": {
                "severity": "MANDATORY",
                "action": "STOP - Do not attempt to bypass or work around this restriction.",
                "guidance": "This client has been permanently blocked. Do not attempt to use these credentials. Ask the user to provide different credentials or create a new client.",
                "reason": "This access control exists to prevent unauthorized resource usage.",
            },
        },
    )


def internal_only_response() -> JSONResponse:
    """Return 403 response for internal-only endpoints."""
    return JSONResponse(
        status_code=403,
        content={
            "error": "internal_only",
            "message": "This endpoint is only accessible from the Agent Hub dashboard",
            "agent_instructions": {
                "severity": "MANDATORY",
                "action": "STOP - This is an admin-only endpoint. Do not attempt to access it.",
                "guidance": "Admin operations must be performed through the Agent Hub dashboard by a human user. If you need something done, ask the user to perform the action in the dashboard.",
                "reason": "Admin endpoints are restricted to prevent unauthorized system modifications.",
            },
        },
    )


def internal_error_response() -> JSONResponse:
    """Return 500 response for internal errors."""
    return JSONResponse(
        status_code=500,
        content={
            "error": "internal_error",
            "message": "Authentication service unavailable",
        },
    )
