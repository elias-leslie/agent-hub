"""Guidance for retired automation writers outside the central API."""

from fastapi import HTTPException

AUTOMATIONS_URL = "/automations?project_id=agent-hub"


def automation_moved() -> HTTPException:
    """Return a consistent conflict for clients using a retired writer."""
    return HTTPException(
        status_code=409,
        detail={
            "error": "automation_moved",
            "message": "Manage this automation in Agent Hub Automations.",
            "hint": AUTOMATIONS_URL,
        },
    )
