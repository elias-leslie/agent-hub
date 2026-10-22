"""Harness groups use only explicit retained producer/ingestion provenance."""

import json
from pathlib import Path
from typing import Any

from sqlalchemy import case, func

from app.models import Session

HARNESSES: dict[str, dict] = json.loads(Path(__file__).with_suffix(".json").read_text())


def harness_options() -> list[dict[str, str]]:
    return [{"id": key, "label": row["label"]} for key, row in HARNESSES.items()] + [{"id": "unknown", "label": "Unknown"}]


def session_harness(session: Any) -> str:
    metadata = getattr(session, "provider_metadata", None)
    metadata = metadata if isinstance(metadata, dict) else {}
    identity = metadata.get("external_identity")
    identity = identity if isinstance(identity, dict) else {}
    explicit = identity.get("harness") or metadata.get("harness")
    for key, row in HARNESSES.items():
        if explicit in row["metadata_values"]:
            return key
    if explicit:
        return "unknown"
    for key, row in HARNESSES.items():
        if getattr(session, "request_source", None) in row["request_sources"]:
            return key
    # This type is written by Pi's canonical native ingestion path.
    return "pi" if getattr(session, "session_type", None) == "pi" else "unknown"


def harness_expression():
    explicit = func.coalesce(func.nullif(Session.provider_metadata["external_identity"]["harness"].as_string(), ""),
                             func.nullif(Session.provider_metadata["harness"].as_string(), ""))
    declared = case(*[(explicit.in_(row["metadata_values"]), key) for key, row in HARNESSES.items()], else_="unknown")
    source = case(*[(Session.request_source.in_(row["request_sources"]), key) for key, row in HARNESSES.items() if row["request_sources"]],
                  (Session.session_type == "pi", "pi"), else_="unknown")
    return case((explicit.is_not(None), declared), else_=source)


def harness_predicate(harness: str):
    if harness not in HARNESSES and harness != "unknown":
        raise ValueError("Unknown harness filter")
    return harness_expression() == harness
