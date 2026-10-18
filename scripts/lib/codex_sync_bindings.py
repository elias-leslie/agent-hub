"""Immutable project bindings for Codex transcript sessions.

Bindings are intentionally separate from the mutable sync checkpoint.  Once a
session is associated with a project, a later process may confirm that same
association but cannot silently move the session to another project.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

STATE_DIR = Path.home() / ".local" / "state" / "codex-session-sync"
BINDINGS_PATH = STATE_DIR / "project-bindings.json"
LOCK_PATH = STATE_DIR / "sync.lock"
SNAPSHOT_VERSION = 1

BindingSource = Literal["explicit", "inherited"]
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SNAPSHOT_FIELDS = frozenset({"version", "bindings"})
_BINDING_FIELDS = frozenset(
    {
        "session_id",
        "project_id",
        "project_root",
        "bound_at",
        "source",
        "parent_session_id",
    }
)
_BINDING_SOURCES = frozenset({"explicit", "inherited"})


def _validated_identifier(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER_RE.fullmatch(value):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _validated_project_root(value: object) -> str:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise ValueError("project_root must be a non-empty absolute path")
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("project_root must be a non-empty absolute path")
    return os.path.normpath(value)


def _validated_bound_at(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("bound_at must be an ISO-8601 timestamp")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("bound_at must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("bound_at must include a timezone")
    return value


def _validated_source(value: object) -> BindingSource:
    if not isinstance(value, str) or value not in _BINDING_SOURCES:
        raise ValueError("source must be 'explicit' or 'inherited'")
    return cast(BindingSource, value)


@dataclass(frozen=True, slots=True)
class ProjectBinding:
    """A session's permanent association with one registered project."""

    session_id: str
    project_id: str
    project_root: str
    bound_at: str
    source: BindingSource
    parent_session_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "session_id",
            _validated_identifier(self.session_id, field="session_id"),
        )
        object.__setattr__(
            self,
            "project_id",
            _validated_identifier(self.project_id, field="project_id"),
        )
        object.__setattr__(self, "project_root", _validated_project_root(self.project_root))
        object.__setattr__(self, "bound_at", _validated_bound_at(self.bound_at))
        object.__setattr__(self, "source", _validated_source(self.source))
        if self.parent_session_id is not None:
            object.__setattr__(
                self,
                "parent_session_id",
                _validated_identifier(self.parent_session_id, field="parent_session_id"),
            )
        if self.source == "explicit" and self.parent_session_id is not None:
            raise ValueError("explicit bindings cannot declare parent_session_id")
        if self.source == "inherited" and self.parent_session_id is None:
            raise ValueError("inherited bindings require parent_session_id")
        if self.parent_session_id == self.session_id:
            raise ValueError("a binding cannot inherit from itself")

    @property
    def fingerprint(self) -> str:
        """Return a stable digest suitable for sync identity comparisons."""

        return binding_fingerprint(self)


class BindingConflict(RuntimeError):
    """Raised when a session is already bound to a different project."""

    def __init__(self, existing: ProjectBinding, requested: ProjectBinding) -> None:
        self.existing = existing
        self.requested = requested
        super().__init__(
            f"session {existing.session_id!r} is already bound to "
            f"{existing.project_id!r} at {existing.project_root!r}"
        )


def _binding_payload(binding: ProjectBinding) -> dict[str, str | None]:
    return {
        "session_id": binding.session_id,
        "project_id": binding.project_id,
        "project_root": binding.project_root,
        "bound_at": binding.bound_at,
        "source": binding.source,
        "parent_session_id": binding.parent_session_id,
    }


def binding_fingerprint(binding: ProjectBinding) -> str:
    """Hash every immutable binding field using canonical JSON."""

    canonical = json.dumps(
        _binding_payload(binding),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _binding_from_payload(session_key: object, payload: object) -> ProjectBinding:
    session_id = _validated_identifier(session_key, field="binding key")
    if not isinstance(payload, dict) or set(payload) != _BINDING_FIELDS:
        raise ValueError("binding entries must contain only the supported fields")
    serialized = cast(dict[str, object], payload)
    parent_value = serialized["parent_session_id"]
    parent_session_id = (
        None
        if parent_value is None
        else _validated_identifier(parent_value, field="parent_session_id")
    )
    binding = ProjectBinding(
        session_id=_validated_identifier(serialized["session_id"], field="session_id"),
        project_id=_validated_identifier(serialized["project_id"], field="project_id"),
        project_root=_validated_project_root(serialized["project_root"]),
        bound_at=_validated_bound_at(serialized["bound_at"]),
        source=_validated_source(serialized["source"]),
        parent_session_id=parent_session_id,
    )
    if binding.session_id != session_id:
        raise ValueError("binding key must match session_id")
    return binding


def load_snapshot(path: Path = BINDINGS_PATH) -> dict[str, ProjectBinding]:
    """Load and validate one atomic binding snapshot."""

    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("project binding snapshot is not valid JSON") from exc
    if not isinstance(payload, dict) or set(payload) != _SNAPSHOT_FIELDS:
        raise ValueError("project binding snapshot must contain only version and bindings")
    if type(payload["version"]) is not int or payload["version"] != SNAPSHOT_VERSION:
        raise ValueError(f"unsupported project binding snapshot version: {payload['version']!r}")
    serialized_bindings = payload["bindings"]
    if not isinstance(serialized_bindings, dict):
        raise ValueError("project binding snapshot bindings must be an object")
    bindings = {
        binding.session_id: binding
        for session_key, serialized in serialized_bindings.items()
        for binding in (_binding_from_payload(session_key, serialized),)
    }
    _validate_binding_graph(bindings)
    return bindings


def _validate_binding_graph(bindings: Mapping[str, ProjectBinding]) -> None:
    for binding in bindings.values():
        if binding.parent_session_id is not None and binding.parent_session_id not in bindings:
            raise ValueError(
                f"inherited binding parent is missing: {binding.parent_session_id}"
            )
        seen: set[str] = set()
        current: ProjectBinding | None = binding
        while current is not None:
            if current.session_id in seen:
                raise ValueError("project binding graph contains a cycle")
            seen.add(current.session_id)
            parent_id = current.parent_session_id
            current = bindings.get(parent_id) if parent_id is not None else None


def _validated_snapshot(bindings: Mapping[str, ProjectBinding]) -> dict[str, ProjectBinding]:
    validated: dict[str, ProjectBinding] = {}
    for session_key, binding in bindings.items():
        session_id = _validated_identifier(session_key, field="binding key")
        if not isinstance(binding, ProjectBinding):
            raise ValueError("binding snapshot values must be ProjectBinding instances")
        if binding.session_id != session_id:
            raise ValueError("binding key must match session_id")
        validated[session_id] = binding
    _validate_binding_graph(validated)
    return validated


def save_snapshot_locked(
    bindings: Mapping[str, ProjectBinding],
    path: Path = BINDINGS_PATH,
) -> None:
    """Atomically save a snapshot while the caller holds :func:`sync_lock`."""

    validated = _validated_snapshot(bindings)
    payload = {
        "version": SNAPSHOT_VERSION,
        "bindings": {
            session_id: _binding_payload(validated[session_id])
            for session_id in sorted(validated)
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fchmod(handle.fileno(), 0o600)
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


@contextmanager
def sync_lock(path: Path = LOCK_PATH) -> Iterator[None]:
    """Serialize binding compare-and-set operations with an advisory file lock."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _timestamp_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def bind_project(
    session_id: str,
    project_id: str,
    project_root: str,
    source: BindingSource,
    parent_session_id: str | None = None,
    *,
    bindings_path: Path = BINDINGS_PATH,
    lock_path: Path = LOCK_PATH,
    bound_at: str | None = None,
) -> ProjectBinding:
    """Compare-and-set a session binding, returning the permanent value."""

    requested = ProjectBinding(
        session_id=session_id,
        project_id=project_id,
        project_root=project_root,
        bound_at=_timestamp_now() if bound_at is None else bound_at,
        source=source,
        parent_session_id=parent_session_id,
    )
    with sync_lock(lock_path):
        bindings = load_snapshot(bindings_path)
        existing = bindings.get(requested.session_id)
        if existing is not None:
            if (
                existing.project_id == requested.project_id
                and existing.project_root == requested.project_root
            ):
                return existing
            raise BindingConflict(existing, requested)
        updated = dict(bindings)
        updated[requested.session_id] = requested
        save_snapshot_locked(updated, bindings_path)
        return requested
