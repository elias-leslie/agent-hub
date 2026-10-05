"""Owner-local durable full extraction records; refocusing never fetches a URL."""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


def _cache_root() -> Path:
    configured = os.environ.get("AGENT_HUB_WEB_CACHE_DIR")
    base = Path(os.environ.get("XDG_CACHE_HOME", str(Path.home() / ".cache")))
    return Path(configured).expanduser().resolve() if configured else (base / "agent-hub/web").resolve()


def save_artifact(payload: dict[str, Any], content: str) -> dict[str, object]:
    root = _cache_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    artifact_id = uuid.uuid4().hex
    path = root / f"{artifact_id}.json"
    record = {**payload, "content": content, "artifact_id": artifact_id, "artifact_version": 1,
              "full_content_chars": len(content), "artifact_content_scope": "full_extracted_text" if payload.get("artifact_kind") != "raw_response" else "raw_response"}
    # Exclusive creation prevents replacing another record; owner-only by default.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(record, handle, ensure_ascii=False)
    return {"artifact_id": artifact_id, "artifact_path": str(path), "full_content_chars": len(content)}


def load_artifact(reference: str) -> dict[str, Any]:
    root = _cache_root()
    if re.fullmatch(r"[a-f0-9]{32}", reference):
        path = root / f"{reference}.json"
    else:
        path = Path(reference).expanduser()
        if not path.is_absolute():
            raise ValueError("artifact must be an owner cache id or absolute owner cache path")
    if path.parent.resolve() != root or not re.fullmatch(r"[a-f0-9]{32}\.json", path.name) or path.is_symlink():
        raise ValueError("artifact path is outside the trusted owner cache")
    try:
        with path.open() as handle:
            record = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"artifact unavailable: {exc}") from exc
    if not isinstance(record, dict) or record.get("artifact_version") != 1 or not isinstance(record.get("content"), str):
        raise ValueError("invalid owner web artifact")
    if record.get("artifact_id") != path.stem:
        raise ValueError("artifact identity mismatch")
    return {**record, "artifact_path": str(path)}
