"""Lightweight agent-progress record (per convergence-map.md cluster D).

The progress record is shared by the agentic HTTP response and several
back-compat re-export points. Extracting it from the deleted sync
tool-loop module keeps the small, immutable shape consumers depend on
while the heavyweight wrapper module is retired.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentProgress:
    """Progress update during agent execution.

    Mirrors the legacy ``app.api.complete.tool_models.AgentProgress`` shape
    that downstream code re-exported via ``tool_handlers``. The HTTP response
    schema now uses this same type, avoiding a duplicate progress model.
    """

    turn: int
    status: str
    message: str
    topic: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_results: list[dict[str, Any]] | None = None
    thinking: str | None = None


__all__ = ["AgentProgress"]
