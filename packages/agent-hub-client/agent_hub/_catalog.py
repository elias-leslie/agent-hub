"""Public read operations for the model catalog, agent list, prompts and health."""

from typing import Any
from urllib.parse import quote

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import ValidationError


def _object(response: httpx.Response, what: str) -> dict[str, Any]:
    if not response.is_success:
        handle_error(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValidationError(f"{what} must be a JSON object")
    return payload


def _agents_params(active_only: bool, limit: int, offset: int) -> dict[str, Any]:
    return {"active_only": str(active_only).lower(), "limit": limit, "offset": offset}


class CatalogOperationsMixin:
    def list_models(self) -> dict[str, Any]:
        """Return the live model catalog (``GET /api/models``)."""
        return _object(self._get_client().get("/api/models", headers=self._inject_tracking_headers("sdk.list_models")), "Model catalog")

    def list_agents(self, *, active_only: bool = True, limit: int = 500, offset: int = 0) -> dict[str, Any]:
        """Return configured agents (``GET /api/agents``)."""
        return _object(self._get_client().get("/api/agents", params=_agents_params(active_only, limit, offset), headers=self._inject_tracking_headers("sdk.list_agents")), "Agent list")

    def get_prompt(self, slug: str) -> dict[str, Any]:
        """Return one stored prompt (``GET /api/prompts/{slug}``)."""
        return _object(self._get_client().get(f"/api/prompts/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_prompt")), "Prompt")

    def health(self) -> dict[str, Any]:
        """Return the service health document (``GET /health``)."""
        return _object(self._get_client().get("/health", headers=self._inject_tracking_headers("sdk.health")), "Health")


class AsyncCatalogOperationsMixin:
    async def list_models(self) -> dict[str, Any]:
        """Return the live model catalog (``GET /api/models``)."""
        client = await self._get_client()
        return _object(await client.get("/api/models", headers=self._inject_tracking_headers("sdk.list_models")), "Model catalog")

    async def list_agents(self, *, active_only: bool = True, limit: int = 500, offset: int = 0) -> dict[str, Any]:
        """Return configured agents (``GET /api/agents``)."""
        client = await self._get_client()
        return _object(await client.get("/api/agents", params=_agents_params(active_only, limit, offset), headers=self._inject_tracking_headers("sdk.list_agents")), "Agent list")

    async def get_prompt(self, slug: str) -> dict[str, Any]:
        """Return one stored prompt (``GET /api/prompts/{slug}``)."""
        client = await self._get_client()
        return _object(await client.get(f"/api/prompts/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_prompt")), "Prompt")

    async def health(self) -> dict[str, Any]:
        """Return the service health document (``GET /health``)."""
        client = await self._get_client()
        return _object(await client.get("/health", headers=self._inject_tracking_headers("sdk.health")), "Health")
