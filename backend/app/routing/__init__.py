"""Routing layer (per convergence-map.md C2).

Routing decisions are produced OUTSIDE the adapter. Inputs: ``agent_slug``,
``workload_profile``, ``task_type``, ``cost_preference``,
``routing_exclude_providers``. Output: ordered list of ``Model[Api]`` to try.
Failed adapters surface as ``AssistantMessage{ stop_reason: "error" }``;
the router catches and tries the next.
"""

from __future__ import annotations
