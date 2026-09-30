"""Validate native identity and caller assertions before session mutation."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from app.constants.projects import get_known_roots

from .adapters.transcript_parsers import transcript_session_metadata


def _deny(code: str, message: str) -> NoReturn:
    from .service import SessionIngestionConflict

    raise SessionIngestionConflict(code, message)


def validate_native_provenance(
    session_id: str | None, project_id: str, parent_session_id: str | None,
    metadata: dict[str, Any], *, previous: dict[str, Any] | None = None,
    transcript_path: str | None = None,
) -> dict[str, Any] | None:
    """Treat the own thread ID as identity; native session_id may name its root."""
    previous = previous or {}
    nested = metadata.get("external_identity")
    nested = nested if isinstance(nested, dict) else {}
    old_nested = previous.get("external_identity")
    old_nested = old_nested if isinstance(old_nested, dict) else {}
    for key in ("runtime_session_id", "agent_path", "aico_project_id"):
        if metadata.get(key) is not None and nested.get(key) is not None and metadata[key] != nested[key]:
            _deny("session_provenance_conflict", f"Conflicting {key} identity assertions.")
        current = nested.get(key, metadata.get(key))
        old = old_nested.get(key, previous.get(key))
        if old is not None and current is not None and old != current:
            _deny("session_provenance_immutable", f"The registered {key} cannot be replaced.")
    runtime_id = nested.get("runtime_session_id", metadata.get("runtime_session_id"))
    if runtime_id is not None and runtime_id != session_id:
        _deny("session_runtime_identity_mismatch", "Runtime identity must name this native thread.")
    if metadata.get("project_id") is not None and metadata["project_id"] != project_id:
        _deny("session_project_provenance_mismatch", "Metadata names a different project.")
    evidence = metadata.get("model_evidence")
    if isinstance(evidence, dict) and evidence.get("session_id") != session_id:
        _deny("session_model_evidence_identity_mismatch", "Model evidence belongs to a different thread.")
    source = transcript_path or metadata.get("transcript_path")
    old_source = previous.get("transcript_path")
    if old_source and source and old_source != source:
        _deny("transcript_source_mismatch", "The registered native transcript source cannot be replaced.")
    if isinstance(evidence, dict) and evidence.get("source_path") not in (None, source):
        _deny("session_model_evidence_source_mismatch", "Model evidence names a different native source.")
    if not isinstance(source, str) or not source:
        return None
    native = transcript_session_metadata(source)
    if native is None or native.get("id") != session_id:
        _deny("transcript_session_identity_mismatch", "The native transcript does not belong to this session.")
    spawn = native.get("source")
    spawn = spawn.get("subagent") if isinstance(spawn, dict) else None
    spawn = spawn.get("thread_spawn") if isinstance(spawn, dict) else None
    spawn = spawn if isinstance(spawn, dict) else {}
    for key in ("parent_thread_id", "agent_path"):
        if native.get(key) is not None and spawn.get(key) is not None and native[key] != spawn[key]:
            _deny("transcript_provenance_conflict", f"Conflicting native {key} assertions.")
    parent = native.get("parent_thread_id", spawn.get("parent_thread_id"))
    if parent != parent_session_id:
        _deny("transcript_parent_mismatch", "The native parent does not match the registered parent.")
    if metadata.get("native_session_id") not in (None, native.get("session_id") or native.get("id")):
        _deny("transcript_runtime_identity_mismatch", "The native root runtime identity does not match.")
    if metadata.get("parent_thread_id") not in (None, parent):
        _deny("transcript_parent_mismatch", "Metadata names a different native parent.")
    agent_path = native.get("agent_path", spawn.get("agent_path"))
    if agent_path is None and parent is None:
        agent_path = "/root"  # Canonical native root path for older headers.
    asserted_path = nested.get("agent_path", metadata.get("agent_path"))
    if asserted_path is not None and agent_path != asserted_path:
        _deny("transcript_agent_path_mismatch", "The native agent path does not match the registered agent path.")
    # Registry roots are the canonical project boundary, independent of caller labels.
    cwd = native.get("cwd")
    if isinstance(cwd, str):
        matching = [
            (name, root) for name, root in get_known_roots().items()
            if Path(cwd).resolve().is_relative_to(Path(root).resolve())
        ]
        if matching and max(matching, key=lambda item: len(item[1]))[0] != project_id:
            _deny("transcript_project_mismatch", "The native working directory belongs to another project.")
    return native
