"""Public read operations: model catalog, agents, prompts, health, execution permission and ownership."""

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


def _agents_params(active_only: bool, limit: int, offset: int, is_coding_agent: bool | None) -> dict[str, Any]:
    params: dict[str, Any] = {"active_only": str(active_only).lower(), "limit": limit, "offset": offset}
    if is_coding_agent is not None:
        params["is_coding_agent"] = str(is_coding_agent).lower()
    return params


def _project_path(project_id: str, suffix: str) -> str:
    return f"/api/{suffix.format(project=quote(project_id, safe=''))}"


class CatalogOperationsMixin:
    def list_models(self) -> dict[str, Any]:
        """Return the live model catalog (``GET /api/models``)."""
        return _object(self._get_client().get("/api/models", headers=self._inject_tracking_headers("sdk.list_models")), "Model catalog")

    def list_agents(
        self, *, active_only: bool = True, limit: int = 500, offset: int = 0, is_coding_agent: bool | None = None,
    ) -> dict[str, Any]:
        """Return configured agents (``GET /api/agents``)."""
        return _object(self._get_client().get("/api/agents", params=_agents_params(active_only, limit, offset, is_coding_agent), headers=self._inject_tracking_headers("sdk.list_agents")), "Agent list")

    def get_prompt(self, slug: str) -> dict[str, Any]:
        """Return one stored prompt (``GET /api/prompts/{slug}``)."""
        return _object(self._get_client().get(f"/api/prompts/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_prompt")), "Prompt")

    def health(self) -> dict[str, Any]:
        """Return the service health document (``GET /health``)."""
        return _object(self._get_client().get("/health", headers=self._inject_tracking_headers("sdk.health")), "Health")

    def get_execution_permission(self, project_id: str) -> dict[str, Any]:
        """Return whether autonomous work may run now (``GET /api/projects/{id}/execution-permission``).

        Keys: ``allowed``, ``permission_tier``, ``auto_exec_enabled``, ``in_time_window``, ``reason``.
        """
        path = _project_path(project_id, "projects/{project}/execution-permission")
        return _object(self._get_client().get(path, headers=self._inject_tracking_headers("sdk.get_execution_permission")), "Execution permission")

    def get_project_ownership(self, project_id: str) -> dict[str, Any]:
        """Return the project's live owners and specialists (``GET /api/ownership/projects/{id}/live``)."""
        path = _project_path(project_id, "ownership/projects/{project}/live")
        return _object(self._get_client().get(path, headers=self._inject_tracking_headers("sdk.get_project_ownership")), "Project ownership")


class AsyncCatalogOperationsMixin:
    async def list_models(self) -> dict[str, Any]:
        """Return the live model catalog (``GET /api/models``)."""
        client = await self._get_client()
        return _object(await client.get("/api/models", headers=self._inject_tracking_headers("sdk.list_models")), "Model catalog")

    async def list_agents(
        self, *, active_only: bool = True, limit: int = 500, offset: int = 0, is_coding_agent: bool | None = None,
    ) -> dict[str, Any]:
        """Return configured agents (``GET /api/agents``)."""
        client = await self._get_client()
        return _object(await client.get("/api/agents", params=_agents_params(active_only, limit, offset, is_coding_agent), headers=self._inject_tracking_headers("sdk.list_agents")), "Agent list")

    async def get_prompt(self, slug: str) -> dict[str, Any]:
        """Return one stored prompt (``GET /api/prompts/{slug}``)."""
        client = await self._get_client()
        return _object(await client.get(f"/api/prompts/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_prompt")), "Prompt")

    async def health(self) -> dict[str, Any]:
        """Return the service health document (``GET /health``)."""
        client = await self._get_client()
        return _object(await client.get("/health", headers=self._inject_tracking_headers("sdk.health")), "Health")

    async def get_execution_permission(self, project_id: str) -> dict[str, Any]:
        """Return whether autonomous work may run now (``GET /api/projects/{id}/execution-permission``)."""
        client = await self._get_client()
        path = _project_path(project_id, "projects/{project}/execution-permission")
        return _object(await client.get(path, headers=self._inject_tracking_headers("sdk.get_execution_permission")), "Execution permission")

    async def get_project_ownership(self, project_id: str) -> dict[str, Any]:
        """Return the project's live owners and specialists (``GET /api/ownership/projects/{id}/live``)."""
        client = await self._get_client()
        path = _project_path(project_id, "ownership/projects/{project}/live")
        return _object(await client.get(path, headers=self._inject_tracking_headers("sdk.get_project_ownership")), "Project ownership")
