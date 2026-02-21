"""Provider API - query upstream provider APIs using stored credentials."""

from __future__ import annotations

import json
import logging
import time

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.adapters.gemini_auth import refresh_gemini_token

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


# ---------------------------------------------------------------------------
# Credential helpers (reuse patterns from gemini.py _resolve_oauth_data)
# ---------------------------------------------------------------------------

def _get_gemini_oauth_data() -> dict | None:
    """Get Gemini OAuth data from credential manager (runs inside backend)."""
    from app.adapters.gemini import get_gemini_vertex_project
    from app.services.credential_manager import get_credential_manager

    cm = get_credential_manager()
    if not cm.is_initialized:
        return None

    token_json = cm.get("gemini", "oauth_token")
    if not token_json:
        return None

    data = json.loads(token_json)
    access_token = data.get("access_token")
    if not access_token:
        return None

    return {
        "access_token": access_token,
        "refresh_token": cm.get("gemini", "refresh_token"),
        "project_id": data.get("project_id") or get_gemini_vertex_project(),
        "expires_at": data.get("expires_at"),
    }


async def _ensure_fresh_token(oauth_data: dict) -> str:
    """Return a valid access token, refreshing if expired."""
    expires_at = oauth_data.get("expires_at")
    if expires_at and time.time() >= (expires_at - 60):
        refresh_token = oauth_data.get("refresh_token")
        if not refresh_token:
            raise HTTPException(400, "Gemini OAuth token expired and no refresh token available")
        creds = await refresh_gemini_token(refresh_token)
        # Persist refreshed token
        from app.services.credential_manager import get_credential_manager

        cm = get_credential_manager()
        cm.set("gemini", "oauth_token", json.dumps({
            "access_token": creds.access_token,
            "refresh_token": creds.refresh_token,
            "expires_at": creds.expires_at,
            "project_id": oauth_data.get("project_id"),
        }))
        if creds.refresh_token:
            cm.set("gemini", "refresh_token", creds.refresh_token)
        return creds.access_token

    return oauth_data["access_token"]


# ---------------------------------------------------------------------------
# Model listing strategies
# ---------------------------------------------------------------------------

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
    from app.config import settings

    api_key = settings.gemini_api_key
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


async def _list_via_oauth(oauth_data: dict) -> list[RemoteModel]:
    """List models using OAuth.

    The generativelanguage.googleapis.com/v1beta/models endpoint rejects
    OAuth bearer tokens (403 "unregistered callers") — it only accepts
    API keys.  CloudCode PA has no model listing endpoint.

    Strategy: use Vertex AI's public model garden catalog which accepts
    OAuth with cloud-platform scope.  We paginate and filter to gemini
    models only.
    """
    access_token = await _ensure_fresh_token(oauth_data)

    all_models: list[RemoteModel] = []
    next_page_token: str | None = None

    async with httpx.AsyncClient(timeout=30.0) as client:
        while True:
            params: dict[str, str | int] = {"pageSize": 100}
            if next_page_token:
                params["pageToken"] = next_page_token

            resp = await client.get(
                "https://us-central1-aiplatform.googleapis.com/v1beta1/publishers/google/models",
                headers={"Authorization": f"Bearer {access_token}"},
                params=params,
            )

            if resp.status_code != 200:
                logger.warning("Vertex AI model list HTTP %s: %s", resp.status_code, resp.text[:200])
                raise HTTPException(502, f"Vertex AI API returned HTTP {resp.status_code}")

            data = resp.json()
            for m in data.get("publisherModels", []):
                # name format: publishers/google/models/gemini-3-pro-preview
                raw_name = m.get("name", "")
                model_id = raw_name.split("/")[-1] if "/" in raw_name else raw_name

                # Only include gemini models
                if not model_id.startswith("gemini"):
                    continue

                # Extract token limits from versionExternalUri or openSourceCategory
                # The Vertex model garden uses a nested structure

                all_models.append(RemoteModel(
                    id=model_id,
                    display_name=m.get("displayName", model_id),
                    description=(m.get("description") or "")[:200],
                ))

            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

    return all_models


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------

@router.get("/{provider}/remote-models", response_model=RemoteModelsResponse)
async def list_remote_models(
    provider: str,
    filter: str | None = None,
) -> RemoteModelsResponse:
    """List models available on the upstream provider API.

    Uses stored credentials (OAuth or API key) to query the provider.
    Optional ``filter`` query param for substring matching on model IDs.
    """
    if provider != "gemini":
        raise HTTPException(400, f"Remote model listing not supported for '{provider}'")

    oauth_data = _get_gemini_oauth_data()
    auth_mode = "oauth" if oauth_data else "api_key"

    if oauth_data:
        models = await _list_via_oauth(oauth_data)
    else:
        models = await _list_via_apikey()

    if filter:
        needle = filter.lower()
        models = [m for m in models if needle in m.id.lower() or needle in m.display_name.lower()]

    models.sort(key=lambda m: m.id)

    return RemoteModelsResponse(
        provider=provider,
        auth_mode=auth_mode,
        models=models,
        total=len(models),
    )
