"""Formatting helpers for the Agent Hub agents CLI."""

from __future__ import annotations

import re
from typing import Any

_SCORE_KEYS = ("coding", "reasoning", "planning", "tool_use", "instruction", "design")
_SCORE_LABELS = {
    "coding": "C",
    "reasoning": "R",
    "planning": "P",
    "tool_use": "T",
    "instruction": "I",
    "design": "D",
    "finance": "F",
    "verification": "V",
    "jenny": "J",
}
_FIT_WEIGHTS = {
    "finance": {"reasoning": 0.60, "planning": 0.25, "instruction": 0.15},
    "verification": {"reasoning": 0.55, "instruction": 0.25, "tool_use": 0.20},
    "jenny": {"planning": 0.45, "reasoning": 0.35, "tool_use": 0.20},
}
_WORD_RE = re.compile(r"[a-z0-9]+")


def agent_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    agents = result.get("agents") if isinstance(result, dict) else None
    return [a for a in agents if isinstance(a, dict)] if isinstance(agents, list) else []


def score_map(models_result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    models = models_result.get("models") if isinstance(models_result, dict) else None
    if not isinstance(models, list):
        return {}
    return {
        str(model["id"]): model
        for model in models
        if isinstance(model, dict) and model.get("id")
    }


def focus_score_key(agent: dict[str, Any]) -> str:
    slug = str(agent.get("slug") or "").lower()
    text = f"{slug} {agent.get('name', '')} {agent.get('description', '')}".lower()
    words = set(_WORD_RE.findall(text))
    if slug == "persona" or words & {"jenny"}:
        return "jenny"
    if slug == "verifier" or words & {"verifier", "verification"}:
        return "verification"
    if words & {"design", "ui", "ux", "mockup", "site", "visual", "image", "designer"}:
        return "design"
    if agent.get("is_coding_agent"):
        return "coding"
    if words & {"finance", "financial", "equity", "trade", "trading", "risk", "investment", "market", "portfolio"}:
        return "finance"
    if words & {"plan", "planner", "planning", "triage", "triager", "supervisor", "orchestrator", "committee"}:
        return "planning"
    if words & {"review", "reviewer", "critic", "audit", "auditor", "validator", "extract", "extractor"}:
        return "instruction"
    if words & {"research", "researcher", "analyst", "reason", "reasoner"}:
        return "reasoning"
    return "instruction"


def model_scores(model: dict[str, Any] | None) -> dict[str, Any]:
    scores = model.get("scores") if isinstance(model, dict) else None
    return scores if isinstance(scores, dict) else {}


def score_value(model: dict[str, Any] | None, key: str) -> str:
    scores = model_scores(model)
    weights = _FIT_WEIGHTS.get(key)
    if weights:
        values = [
            float(scores[score_key]) * weight
            for score_key, weight in weights.items()
            if isinstance(scores.get(score_key), (int, float))
        ]
        value = round(sum(values)) if len(values) == len(weights) else None
    else:
        value = scores.get(key)
    return str(value) if value is not None else "-"


def format_score_vector(model: dict[str, Any] | None) -> str:
    scores = model_scores(model)
    parts = []
    for key in _SCORE_KEYS:
        value = scores.get(key)
        parts.append(f"{_SCORE_LABELS[key]}{value if value is not None else '-'}")
    return " ".join(parts)


def print_table(headers: list[str], rows: list[list[str]]) -> None:
    widths = [
        max(len(headers[i]), *(len(row[i]) for row in rows)) if rows else len(headers[i])
        for i in range(len(headers))
    ]
    print("  ".join(headers[i].ljust(widths[i]) for i in range(len(headers))))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        print("  ".join(row[i].ljust(widths[i]) for i in range(len(headers))))


def format_memory_summary(agent: dict[str, Any]) -> str:
    config = agent.get("memory_config")
    if not isinstance(config, dict):
        return "memory=-"
    parts = []
    if config.get("injection_enabled") is not None:
        parts.append(f"inject={str(bool(config.get('injection_enabled'))).lower()}")
    for label, key in [
        ("mandates", "include_mandates"),
        ("guardrails", "include_guardrails"),
        ("refs", "include_references"),
        ("continuity", "continuity_enabled"),
    ]:
        if config.get(key) is not None:
            parts.append(f"{label}={str(bool(config.get(key))).lower()}")
    audience = config.get("audience_tags")
    if isinstance(audience, list) and audience:
        parts.append(f"audience={','.join(str(item) for item in audience[:4])}")
    return "memory=" + (" ".join(parts) if parts else "configured")


def print_agent_detail(agent: dict[str, Any]) -> None:
    fallbacks = [str(item) for item in agent.get("fallback_models") or []]
    fallback_text = ",".join(fallbacks) if fallbacks else "-"
    print(
        f"{agent['slug']} | primary={agent['primary_model_id']} | "
        f"fallbacks={fallback_text} | escalation={agent.get('escalation_model_id') or '-'} | "
        f"version={agent['version']}"
    )
    print(
        f"  active={agent['is_active']} coding={agent['is_coding_agent']} "
        f"thinking={agent.get('thinking_level') or '-'} temp={agent['temperature']} "
        f"timeout={agent.get('timeout_seconds') or '-'}"
    )
    print(f"  {format_memory_summary(agent)}")


def _version_config(version: dict[str, Any]) -> dict[str, Any]:
    config = version.get("config_snapshot")
    return config if isinstance(config, dict) else {}


def print_agent_versions(versions: list[dict[str, Any]]) -> None:
    print(f"AGENT_VERSIONS[{len(versions)}]")
    rows: list[list[str]] = []
    for item in versions:
        config = _version_config(item)
        fallbacks = config.get("fallback_models") or []
        if not isinstance(fallbacks, list):
            fallbacks = []
        reason = str(item.get("change_reason") or "-").replace("\n", " ")
        if len(reason) > 90:
            reason = reason[:87] + "..."
        rows.append([
            str(item.get("version") or "-"),
            str(config.get("primary_model_id") or "-"),
            ",".join(str(model) for model in fallbacks) or "-",
            str(config.get("escalation_model_id") or "-"),
            str(config.get("thinking_level") or "-"),
            reason,
            str(item.get("created_at") or "-"),
        ])
    print_table(["ver", "primary", "fallbacks", "escalation", "think", "reason", "created"], rows)


def print_agent_activity(payload: dict[str, Any]) -> None:
    sessions = payload.get("sessions") if isinstance(payload, dict) else None
    requests = payload.get("requests") if isinstance(payload, dict) else None
    session_rows = [row for row in sessions if isinstance(row, dict)] if isinstance(sessions, list) else []
    request_rows = [row for row in requests if isinstance(row, dict)] if isinstance(requests, list) else []
    print(f"AGENT_ACTIVITY[{payload.get('agent_slug', '-')}] sessions={len(session_rows)} requests={len(request_rows)}")
    if session_rows:
        rows = []
        for row in session_rows:
            models = row.get("models_used") if isinstance(row.get("models_used"), list) else []
            rows.append([
                str(row.get("created_at") or "-"),
                str(row.get("id") or "-"),
                str(row.get("external_id") or "-"),
                str(row.get("model") or "-"),
                ",".join(str(model) for model in models) or "-",
                str(row.get("status") or "-"),
                str(row.get("health_detail") or "-"),
            ])
        print_table(["created", "session", "external", "model", "used", "status", "health"], rows)
    if request_rows:
        rows = []
        for row in request_rows:
            rows.append([
                str(row.get("created_at") or "-"),
                str(row.get("session_id") or "-"),
                str(row.get("model") or "-"),
                str(row.get("status_code") or "-"),
                str(row.get("latency_ms") or "-"),
                "yes" if row.get("timed_out") else "no",
                str(row.get("fallback_model") or "-") if row.get("used_fallback") else "-",
            ])
        print_table(["created", "session", "model", "code", "ms", "timeout", "fallback"], rows)


def format_slugs(agents: list[dict[str, Any]], limit: int = 8) -> str:
    slugs = [str(a.get("slug") or "-") for a in sorted(agents, key=lambda a: str(a.get("slug") or ""))]
    if len(slugs) <= limit:
        return ",".join(slugs)
    return f"{','.join(slugs[:limit])},+{len(slugs) - limit}"


def print_compact_agents(
    result: dict[str, Any],
    *,
    with_scores: bool,
    scores_by_model: dict[str, dict[str, Any]],
) -> None:
    agents = agent_items(result)
    total = result.get("total", len(agents))
    print(f"AGENTS[{len(agents)} shown/{total} total]")
    headers = ["slug", "kind", "focus", "fit", "primary", "fb", "esc"]
    if with_scores:
        headers.append("scores")
    rows: list[list[str]] = []
    for agent in agents:
        model_id = str(agent.get("primary_model_id") or "-")
        model = scores_by_model.get(model_id)
        focus = focus_score_key(agent)
        row = [
            str(agent.get("slug") or "-"),
            "code" if agent.get("is_coding_agent") else "text",
            _SCORE_LABELS[focus],
            score_value(model, focus),
            model_id,
            str(len(agent.get("fallback_models") or [])),
            str(agent.get("escalation_model_id") or "-"),
        ]
        if with_scores:
            row.append(format_score_vector(model))
        rows.append(row)
    print_table(headers, rows)


def print_agents_by_model(
    result: dict[str, Any],
    *,
    scores_by_model: dict[str, dict[str, Any]],
) -> None:
    agents = agent_items(result)
    grouped: dict[str, list[dict[str, Any]]] = {}
    for agent in agents:
        grouped.setdefault(str(agent.get("primary_model_id") or "-"), []).append(agent)
    rows: list[list[str]] = []
    for model_id, model_agents in sorted(grouped.items(), key=lambda item: (-len(item[1]), item[0])):
        model = scores_by_model.get(model_id)
        rows.append([
            model_id,
            str(len(model_agents)),
            format_score_vector(model),
            format_slugs(model_agents),
        ])
    print(f"AGENT_MODELS[{len(grouped)} primary models/{len(agents)} agents]")
    print_table(["primary", "agents", "scores", "slugs"], rows)
