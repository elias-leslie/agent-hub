"""Provider API - query upstream provider APIs using stored credentials."""

from __future__ import annotations

import logging

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/providers", tags=["providers"])


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

class RemoteModel(BaseModel):
    """A model available on the upstream provider."""

    id: str
    display_name: str
    description: str = ""
    input_token_limit: int = 0
    output_token_limit: int = 0


class RemoteModelsResponse(BaseModel):
    """Response for remote models listing."""

    provider: str
    auth_mode: str
    models: list[RemoteModel]
    total: int


def _parse_genai_models(data: dict) -> list[RemoteModel]:
    """Parse models from generativelanguage.googleapis.com response."""
    models = []
    for m in data.get("models", []):
        model_id = m.get("name", "").replace("models/", "")
        if not model_id:
            continue
        models.append(RemoteModel(
            id=model_id,
            display_name=m.get("displayName", model_id),
            description=(m.get("description") or "")[:200],
            input_token_limit=m.get("inputTokenLimit", 0),
            output_token_limit=m.get("outputTokenLimit", 0),
        ))
    return models


async def _list_via_apikey() -> list[RemoteModel]:
    """List models using Gemini API key."""
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    api_key = cm.get_api_key("gemini") if cm.is_initialized else None
    if not api_key:
        raise HTTPException(400, "No Gemini API key configured")

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": api_key, "pageSize": 1000},
        )

    if resp.status_code != 200:
        raise HTTPException(502, f"Google API returned HTTP {resp.status_code}")

    return _parse_genai_models(resp.json())


@router.get("/{provider}/remote-models", response_model=RemoteModelsResponse)
async def list_remote_models(
    provider: str,
    filter: str | None = None,
) -> RemoteModelsResponse:
    """List models available on the upstream provider API.

    Uses stored Gemini API keys to query the provider.
    Optional ``filter`` query param for substring matching on model IDs.
    """
    if provider != "gemini":
        raise HTTPException(400, f"Remote model listing not supported for '{provider}'")

    models = await _list_via_apikey()

    if filter:
        needle = filter.lower()
        models = [m for m in models if needle in m.id.lower() or needle in m.display_name.lower()]

    models.sort(key=lambda m: m.id)

    return RemoteModelsResponse(
        provider=provider,
        auth_mode="api_key",
        models=models,
        total=len(models),
    )
