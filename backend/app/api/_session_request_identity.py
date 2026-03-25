"""Helpers for enriching session requests with request attribution."""

from __future__ import annotations

from typing import Any

from fastapi import Request

from app.middleware.access_control_constants import (
    CLIENT_ID_HEADER,
    REQUEST_SOURCE_HEADER,
    SOURCE_CLIENT_HEADER,
    SOURCE_PATH_HEADER,
)
from app.services.session_ingestion import SessionHeartbeatRequest, SessionUpsertRequest


def _header_value(request: Request, header_name: str) -> str | None:
    value = request.headers.get(header_name)
    return value if isinstance(value, str) and value else None


def _state_value(request: Request, attr_name: str) -> str | None:
    value = getattr(request.state, attr_name, None)
    return value if isinstance(value, str) and value else None


def _merge_provider_metadata(
    current: dict[str, Any] | None,
    request: Request,
) -> dict[str, Any]:
    merged = dict(current or {})
    source_client = _header_value(request, SOURCE_CLIENT_HEADER)
    source_path = _header_value(request, SOURCE_PATH_HEADER)
    if source_client:
        merged["source_client"] = source_client
    if source_path:
        merged["source_path"] = source_path
    return merged


def enrich_session_upsert_request(
    payload: SessionUpsertRequest,
    request: Request,
) -> SessionUpsertRequest:
    """Apply request-derived attribution to an upsert request."""
    return payload.model_copy(
        update={
            "client_id": _header_value(request, CLIENT_ID_HEADER)
            or _state_value(request, "client_id")
            or payload.client_id,
            "request_source": _header_value(request, REQUEST_SOURCE_HEADER)
            or _state_value(request, "request_source")
            or payload.request_source,
            "provider_metadata": _merge_provider_metadata(payload.provider_metadata, request),
        }
    )


def enrich_session_heartbeat_request(
    payload: SessionHeartbeatRequest,
    request: Request,
) -> SessionHeartbeatRequest:
    """Apply request-derived attribution to a heartbeat request."""
    return payload.model_copy(
        update={
            "client_id": _header_value(request, CLIENT_ID_HEADER)
            or _state_value(request, "client_id")
            or payload.client_id,
            "request_source": _header_value(request, REQUEST_SOURCE_HEADER)
            or _state_value(request, "request_source")
            or payload.request_source,
            "provider_metadata": _merge_provider_metadata(payload.provider_metadata, request),
        }
    )
