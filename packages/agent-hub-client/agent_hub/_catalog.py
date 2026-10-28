"""Public read operations: model catalog, agents, prompts, health and ownership."""

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

    def model_selection_policy(self) -> dict[str, Any]:
        """List configured task types and policy version."""
        return _object(self._get_client().get("/api/models/selection-policy", headers=self._inject_tracking_headers("sdk.model_selection_policy")), "Model selection policy")

    def select_model(self, task_type: str, **options: Any) -> dict[str, Any]:
        """Get metadata-only model advice; no task contents are accepted."""
        return _object(self._get_client().post("/api/models/select", json={"task_type": task_type, **options}, headers=self._inject_tracking_headers("sdk.select_model")), "Model selection")

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

    def get_project_ownership(self, project_id: str) -> dict[str, Any]:
        """Return the project's live owners and specialists (``GET /api/ownership/projects/{id}/live``)."""
        path = _project_path(project_id, "ownership/projects/{project}/live")
        return _object(self._get_client().get(path, headers=self._inject_tracking_headers("sdk.get_project_ownership")), "Project ownership")


class AsyncCatalogOperationsMixin:
    async def list_models(self) -> dict[str, Any]:
        """Return the live model catalog (``GET /api/models``)."""
        client = await self._get_client()
        return _object(await client.get("/api/models", headers=self._inject_tracking_headers("sdk.list_models")), "Model catalog")

    async def model_selection_policy(self) -> dict[str, Any]:
        """List configured task types and policy version."""
        client = await self._get_client()
        return _object(await client.get("/api/models/selection-policy", headers=self._inject_tracking_headers("sdk.model_selection_policy")), "Model selection policy")

    async def select_model(self, task_type: str, **options: Any) -> dict[str, Any]:
        """Get metadata-only model advice; no task contents are accepted."""
        client = await self._get_client()
        return _object(await client.post("/api/models/select", json={"task_type": task_type, **options}, headers=self._inject_tracking_headers("sdk.select_model")), "Model selection")

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

    async def get_project_ownership(self, project_id: str) -> dict[str, Any]:
        """Return the project's live owners and specialists (``GET /api/ownership/projects/{id}/live``)."""
        client = await self._get_client()
        path = _project_path(project_id, "ownership/projects/{project}/live")
        return _object(await client.get(path, headers=self._inject_tracking_headers("sdk.get_project_ownership")), "Project ownership")
