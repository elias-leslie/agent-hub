"""Canonical read-only agent metadata and context preview operations."""
from typing import Any
from urllib.parse import quote

import httpx

from agent_hub._utils import handle_error
from agent_hub.exceptions import ValidationError


def _agent_payload(response: httpx.Response) -> dict[str, Any]:
    if not response.is_success:
        handle_error(response)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValidationError("Agent metadata must be a JSON object")
    return payload


class AgentOperationsMixin:
    def get_agent(self, slug: str) -> dict[str, Any]:
        return _agent_payload(self._get_client().get(f"/api/agents/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_agent")))

    def preview_agent(self, slug: str, *, project_id: str | None = None) -> dict[str, Any]:
        return _agent_payload(self._get_client().get(f"/api/agents/{quote(slug, safe='')}/preview", params={"project_id": project_id} if project_id else {}, headers=self._inject_tracking_headers("sdk.preview_agent")))


class AsyncAgentOperationsMixin:
    async def get_agent(self, slug: str) -> dict[str, Any]:
        client = await self._get_client()
        return _agent_payload(await client.get(f"/api/agents/{quote(slug, safe='')}", headers=self._inject_tracking_headers("sdk.get_agent")))

    async def preview_agent(self, slug: str, *, project_id: str | None = None) -> dict[str, Any]:
        client = await self._get_client()
        return _agent_payload(await client.get(f"/api/agents/{quote(slug, safe='')}/preview", params={"project_id": project_id} if project_id else {}, headers=self._inject_tracking_headers("sdk.preview_agent")))
