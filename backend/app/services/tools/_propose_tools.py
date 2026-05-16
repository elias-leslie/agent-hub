"""Executors for Vantage's mode-recommendation tools.

These tools don't perform work — they emit a structured JSON recommendation
the consumer normalizes into a ``mode_recommendation`` event for the user UI.

The output JSON shape matches Vantage's ``ModeRecommendation`` type
(frontend/src/lib/research/types.ts):

    {
        "recommended": "thorough" | "committee" | "honing",
        "reason": str,
        "declined": "honing" | None,
        "missing": [str],            # only when refusing
        "proposal": {                 # only for honing-accepted
            "editable_asset": {...},
            "metric": {...},
            "hypothesis": str,
        },
    }
"""

from __future__ import annotations

import json
from typing import Any


def _emit(payload: dict[str, Any]) -> str:
    """JSON-serialize the recommendation for the tool_result content."""
    return json.dumps(payload, ensure_ascii=False)


def execute_propose_thorough(args: dict[str, Any]) -> str:
    reason = str(args.get("reason") or "agent recommends a wider read + critique pass")
    return _emit({"recommended": "thorough", "reason": reason})


def execute_propose_committee(args: dict[str, Any]) -> str:
    reason = str(args.get("reason") or "agent recommends a multi-persona debate")
    return _emit({"recommended": "committee", "reason": reason})


def execute_propose_honing(args: dict[str, Any]) -> str:
    """Validate the honing proposal; return either an accepted spec or a
    Thorough-mode fallback listing the missing slots.

    Honing requires BOTH:
      - editable_asset with at minimum ``path`` and ``kind``.
      - metric with both ``kind`` and ``spec``.

    Mirrors ``validate_honing_proposal`` in vantage's research_orchestrator.py
    so the propose path agrees with the runtime path.
    """

    asset_raw = args.get("editable_asset")
    metric_raw = args.get("metric")
    asset: dict[str, Any] = asset_raw if isinstance(asset_raw, dict) else {}
    metric: dict[str, Any] = metric_raw if isinstance(metric_raw, dict) else {}
    reason = str(args.get("reason") or "agent recommends metric-driven honing")

    missing: list[str] = []
    if not asset or not asset.get("path") or not asset.get("kind"):
        missing.append("editable_asset")
    if not metric or not metric.get("kind") or not metric.get("spec"):
        missing.append("metric")

    if missing:
        return _emit(
            {
                "recommended": "thorough",
                "declined": "honing",
                "missing": missing,
                "reason": (
                    f"honing requires fully-specified {' and '.join(missing)}; "
                    "falling back to Thorough mode"
                ),
            }
        )

    asset_out: dict[str, Any] = {
        "path": asset["path"],
        "kind": asset["kind"],
    }
    current_content = asset.get("current_content")
    if isinstance(current_content, str):
        asset_out["current_content_preview"] = current_content[:240]

    proposal: dict[str, Any] = {
        "editable_asset": asset_out,
        "metric": {
            "kind": metric["kind"],
            "spec": metric["spec"],
        },
    }
    hypothesis = args.get("hypothesis")
    if isinstance(hypothesis, str) and hypothesis:
        proposal["hypothesis"] = hypothesis

    return _emit(
        {
            "recommended": "honing",
            "reason": reason,
            "proposal": proposal,
        }
    )
