"""Routing layer (per convergence-map.md C2).

Routing decisions are produced outside the adapter. Input: ``agent_slug``.
Output: the model chain assigned to that registered agent. Failed adapters
surface as ``AssistantMessage{ stop_reason: "error" }``; fallback execution
tries the next assigned model.
"""

from __future__ import annotations
