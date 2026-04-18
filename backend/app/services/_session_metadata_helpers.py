"""Private helpers for extracting session metadata fields."""

from typing import Any

from app.constants.catalog import MODEL_CATALOG_BY_ID
from app.models import Session
from app.services.agent_routing import get_provider_for_model


def resolve_model_display_name(model_id: str | None) -> str | None:
    if not model_id:
        return None
    normalized = model_id.split("/")[-1] if "/" in model_id else model_id
    entry = MODEL_CATALOG_BY_ID.get(normalized) or MODEL_CATALOG_BY_ID.get(model_id)
    return entry.name if entry else None


def session_metadata(session: Session) -> dict[str, Any]:
    metadata = session.provider_metadata if isinstance(session.provider_metadata, dict) else None
    return metadata or {}


def metadata_paths(metadata: dict[str, Any] | None) -> list[str]:
    if not isinstance(metadata, dict):
        return []
    paths: list[str] = []
    seen: set[str] = set()
    for key in ("cwd", "repo_root"):
        value = metadata.get(key)
        if isinstance(value, str) and value and value not in seen:
            paths.append(value)
            seen.add(value)
    return paths


def metadata_value(session: Session, key: str) -> str | None:
    value = session_metadata(session).get(key)
    return value if isinstance(value, str) and value else None


def list_first(values: object) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    first = values[0]
    return first if isinstance(first, str) else None


def list_last(values: object) -> str | None:
    if not isinstance(values, list) or not values:
        return None
    last = values[-1]
    return last if isinstance(last, str) else None


def optional_str(value: object) -> str | None:
    return value if isinstance(value, str) else None


def scope_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def working_dir(session: Session) -> str | None:
    return metadata_value(session, "cwd")


def repo_root(session: Session) -> str | None:
    return metadata_value(session, "repo_root")


def source_client(session: Session) -> str | None:
    return metadata_value(session, "source_client")


def source_path(session: Session) -> str | None:
    return metadata_value(session, "source_path")


def session_attribution(session: Session) -> dict[str, str | None]:
    request_source = optional_str(session.request_source)
    logical_client = source_client(session)

    if request_source and request_source.startswith("manual/caveman"):
        return {
            "attribution_kind": "benchmark",
            "attribution_label": "Benchmark",
            "attribution_detail": request_source,
        }

    if request_source and request_source.startswith("verification/"):
        return {
            "attribution_kind": "verification",
            "attribution_label": "Verification",
            "attribution_detail": request_source,
        }

    if request_source and (
        request_source.startswith("persona_wake:")
        or request_source == "codex-transcript-sync"
    ):
        return {
            "attribution_kind": "system",
            "attribution_label": "System",
            "attribution_detail": request_source,
        }

    if request_source == "consultation":
        return {
            "attribution_kind": "consultation",
            "attribution_label": "Consultation",
            "attribution_detail": request_source,
        }

    if request_source == "summitflow" or logical_client == "summitflow":
        return {
            "attribution_kind": "autonomous",
            "attribution_label": "Autonomous",
            "attribution_detail": request_source or logical_client,
        }

    return {
        "attribution_kind": "user",
        "attribution_label": "User",
        "attribution_detail": request_source or logical_client,
    }


def requested_model(session: Session) -> str:
    return metadata_value(session, "requested_model") or list_first(session.models_used) or str(session.model)


def effective_model(session: Session) -> str:
    return metadata_value(session, "effective_model") or list_last(session.models_used) or str(session.model)


def requested_provider(session: Session, req_model: str) -> str:
    return (
        metadata_value(session, "requested_provider")
        or list_first(session.providers_used)
        or get_provider_for_model(req_model)
    )


def effective_provider(session: Session, eff_model: str) -> str:
    return (
        metadata_value(session, "effective_provider")
        or list_last(session.providers_used)
        or get_provider_for_model(eff_model)
    )


def fallback_used(session: Session, req_model: str, eff_model: str) -> bool:
    fallback_value = session_metadata(session).get("fallback_used")
    return fallback_value if isinstance(fallback_value, bool) else req_model != eff_model


def session_model_info(session: Session) -> dict[str, str | bool | None]:
    req_model = requested_model(session)
    eff_model = effective_model(session)
    return {
        "requested_model": req_model,
        "effective_model": eff_model,
        "requested_provider": requested_provider(session, req_model),
        "effective_provider": effective_provider(session, eff_model),
        "fallback_used": fallback_used(session, req_model, eff_model),
        "fallback_reason": metadata_value(session, "fallback_reason"),
    }
