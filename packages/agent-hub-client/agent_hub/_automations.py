"""Automation-owner operations: central profiles and run callbacks.

These endpoints require the owner's internal service secret, passed per call
like the native-ingestion operations.
"""

from typing import Any
from urllib.parse import quote

from agent_hub._catalog import _object


def _owner_headers(secret: str) -> dict[str, str]:
    if not secret:
        raise ValueError("internal_secret is required for automation-owner operations")
    return {"X-Agent-Hub-Internal": secret}


def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    items = payload.get("items")
    if not isinstance(items, list):
        from agent_hub.exceptions import ValidationError

        raise ValidationError("Automation profiles response has no items list")
    return items


class AutomationOperationsMixin:
    def list_automation_profiles(self, project_id: str, *, internal_secret: str, limit: int = 100) -> list[dict[str, Any]]:
        response = self._get_client().get("/api/automations/profiles", params={"project_id": project_id, "limit": limit}, headers=self._inject_tracking_headers("sdk.list_automation_profiles", _owner_headers(internal_secret)))
        return _items(_object(response, "Automation profiles"))

    def complete_automation_run(self, run_id: str, result: dict[str, Any], *, internal_secret: str) -> dict[str, Any]:
        response = self._get_client().post(f"/api/automations/runs/{quote(run_id, safe='')}/complete", json=result, headers=self._inject_tracking_headers("sdk.complete_automation_run", _owner_headers(internal_secret)))
        return _object(response, "Automation run")

    def accept_automation_run(self, run_id: str, receipt: dict[str, Any], *, internal_secret: str) -> dict[str, Any]:
        response = self._get_client().post(f"/api/automations/runs/{quote(run_id, safe='')}/accept", json=receipt, headers=self._inject_tracking_headers("sdk.accept_automation_run", _owner_headers(internal_secret)))
        return _object(response, "Automation run")


class AsyncAutomationOperationsMixin:
    async def list_automation_profiles(self, project_id: str, *, internal_secret: str, limit: int = 100) -> list[dict[str, Any]]:
        client = await self._get_client()
        response = await client.get("/api/automations/profiles", params={"project_id": project_id, "limit": limit}, headers=self._inject_tracking_headers("sdk.list_automation_profiles", _owner_headers(internal_secret)))
        return _items(_object(response, "Automation profiles"))

    async def complete_automation_run(self, run_id: str, result: dict[str, Any], *, internal_secret: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.post(f"/api/automations/runs/{quote(run_id, safe='')}/complete", json=result, headers=self._inject_tracking_headers("sdk.complete_automation_run", _owner_headers(internal_secret)))
        return _object(response, "Automation run")

    async def accept_automation_run(self, run_id: str, receipt: dict[str, Any], *, internal_secret: str) -> dict[str, Any]:
        client = await self._get_client()
        response = await client.post(f"/api/automations/runs/{quote(run_id, safe='')}/accept", json=receipt, headers=self._inject_tracking_headers("sdk.accept_automation_run", _owner_headers(internal_secret)))
        return _object(response, "Automation run")
