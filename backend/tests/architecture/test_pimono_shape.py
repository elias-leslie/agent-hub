"""Guardrails for the pi-mono convergence shape.

HTTP response, persistence, analytics export, and response-cache records are
explicit boundary contracts. The direct tool runtime is the caller-side
execution bridge for ``complete_internal``. Those boundary cases are documented
allow-list entries; everything else must stay on the universal ``app.llm``
surface.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
LEGACY_RESULT_FIELDS = {
    "cache_metrics",
    "cited_uuids",
    "container",
    "container_id",
    "content",
    "error",
    "error_summary",
    "fallback_reason",
    "finish_reason",
    "from_cache",
    "input_tokens",
    "memory_uuids",
    "model",
    "output_tokens",
    "progress_log",
    "provider",
    "raw_response",
    "session_id",
    "status",
    "thinking_content",
    "thinking_tokens",
    "tool_calls",
    "tool_calls_count",
    "turns",
}
RESULT_SHAPE_ALLOWLIST = {
    (APP / "api" / "admin_schemas.py", "LowYieldSessionRow"),
    (APP / "api" / "complete" / "response_schemas.py", "CompletionResponse"),
    (APP / "api" / "complete" / "response_schemas.py", "StreamingChunk"),
    (APP / "models" / "agent_benchmark.py", "AgentBenchmarkAttempt"),
    (APP / "models" / "agent_performance_log.py", "AgentPerformanceLog"),
    (APP / "models" / "session.py", "NativeContinuationTurn"),
    (APP / "services" / "analytics" / "models.py", "CostLogExportRow"),
    (APP / "services" / "completion" / "types.py", "CompletionServiceResult"),
    (APP / "services" / "response_cache" / "models.py", "CachedResponse"),
}
TOOL_FILE_ALLOWLIST = {
    APP / "llm" / "tool_loop.py",
    # Live service-side tool runtime used by complete_internal/build_direct_tool_runner.
    APP / "services" / "tools" / "tool_handler.py",
}
CANONICAL_PREINJECTION_ALLOWLIST = {
    APP / "api" / "complete" / "complete_execution.py",
    APP / "api" / "complete" / "execution.py",
    APP / "services" / "agent_routing_completion.py",
    APP / "services" / "completion" / "service.py",
    APP / "workflows" / "completion.py",
}


@pytest.fixture(scope="module")
def app_trees() -> dict[Path, ast.Module]:
    """Parse every app module once for all shape checks."""
    return {
        path: ast.parse(path.read_text(), filename=str(path))
        for path in APP.rglob("*.py")
        if "__pycache__" not in path.parts
    }


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _class_fields(node: ast.ClassDef) -> set[str]:
    fields: set[str] = set()
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields.add(stmt.target.id)
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    fields.add(target.id)
    return fields


def test_no_legacy_completion_result_shaped_classes_remain(
    app_trees: dict[Path, ast.Module],
) -> None:
    offenders: list[str] = []
    for path, tree in app_trees.items():
        if path == APP / "llm" / "types.py":
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            if (path, node.name) in RESULT_SHAPE_ALLOWLIST:
                continue
            overlap = _class_fields(node) & LEGACY_RESULT_FIELDS
            if len(overlap) >= 5:
                offenders.append(f"{path.relative_to(BACKEND)}:{node.name}:{sorted(overlap)}")
    assert offenders == []


def test_tool_loop_file_family_stays_collapsed() -> None:
    """Allow-list the direct tool runtime; it is not a provider tool loop."""

    offenders = [
        path.relative_to(BACKEND).as_posix()
        for pattern in ("*tool_loop*.py", "*tool_executor*.py", "*tool_handler*.py")
        for path in APP.rglob(pattern)
        if path not in TOOL_FILE_ALLOWLIST
    ]
    assert offenders == []


def test_canonical_context_preinjection_bypass_stays_narrowly_allowlisted(
    app_trees: dict[Path, ast.Module],
) -> None:
    """Only paths that first build canonical delivery may skip reinjection."""
    users: set[Path] = set()
    for path, tree in app_trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            for keyword in node.keywords:
                if keyword.arg != "canonical_context_preinjected":
                    continue
                users.add(path)
    assert users == CANONICAL_PREINJECTION_ALLOWLIST


def test_each_provider_module_registers_exactly_once(
    app_trees: dict[Path, ast.Module],
) -> None:
    offenders: list[str] = []
    for path in (APP / "llm" / "providers").glob("*.py"):
        if path.name == "__init__.py":
            continue
        count = sum(
            1
            for node in ast.walk(app_trees[path])
            if isinstance(node, ast.Call) and _call_name(node.func) == "register_api_provider"
        )
        if count != 1:
            offenders.append(f"{path.relative_to(BACKEND)}:{count}")
    assert offenders == []
