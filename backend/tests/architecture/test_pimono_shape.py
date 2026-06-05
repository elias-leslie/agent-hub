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
    (APP / "api" / "orchestration_models.py", "SubagentResponse"),
    (APP / "api" / "orchestration_models.py", "WorkflowStageResponse"),
    (APP / "api" / "persona" / "schema_improvement.py", "PersonaHeartbeatFieldSession"),
    (APP / "models" / "agent_benchmark.py", "AgentBenchmarkAttempt"),
    (APP / "models" / "agent_performance_log.py", "AgentPerformanceLog"),
    (APP / "services" / "analytics" / "models.py", "CostLogExportRow"),
    (APP / "services" / "completion" / "types.py", "CompletionServiceResult"),
    (APP / "services" / "orchestration" / "subagent_models.py", "SubagentResult"),
    (APP / "services" / "response_cache" / "models.py", "CachedResponse"),
}
TOOL_FILE_ALLOWLIST = {
    APP / "llm" / "tool_loop.py",
    # Live service-side tool runtime used by complete_internal/build_direct_tool_runner.
    APP / "services" / "tools" / "tool_handler.py",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


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


def test_api_provider_protocol_is_pi_mono_two_method_surface() -> None:
    tree = _tree(APP / "llm" / "api_registry.py")
    api_provider = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "ApiProvider"
    )
    methods = {
        stmt.name
        for stmt in api_provider.body
        if isinstance(stmt, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    assert methods == {"stream", "stream_simple"}


def test_no_legacy_completion_result_shaped_classes_remain() -> None:
    offenders: list[str] = []
    for path in APP.rglob("*.py"):
        if "__pycache__" in path.parts or path == APP / "llm" / "types.py":
            continue
        tree = _tree(path)
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


def test_each_provider_module_registers_exactly_once() -> None:
    offenders: list[str] = []
    for path in (APP / "llm" / "providers").glob("*.py"):
        if path.name == "__init__.py":
            continue
        count = sum(
            1
            for node in ast.walk(_tree(path))
            if isinstance(node, ast.Call) and _call_name(node.func) == "register_api_provider"
        )
        if count != 1:
            offenders.append(f"{path.relative_to(BACKEND)}:{count}")
    assert offenders == []
