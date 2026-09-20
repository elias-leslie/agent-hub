"""Focused tests for durable SummitFlow technical recovery dispatch."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.services.context_maintenance_tasks import (
    dispatch_technical_work,
    reconcile_technical_work,
)


def _permission(*, allowed: bool, reason: str) -> SimpleNamespace:
    return SimpleNamespace(
        allowed=allowed,
        permission_tier="full",
        auto_exec_enabled=allowed,
        in_time_window=True,
        reason=reason,
    )


@pytest.fixture(autouse=True)
def _project_execution_permission() -> Iterator[AsyncMock]:
    with patch(
        "app.services.context_maintenance_tasks.check_execution_permission",
        new=AsyncMock(return_value=_permission(allowed=True, reason="allowed")),
    ) as permission:
        yield permission


def _item(*, status: str | None = None, task_id: str | None = None, generation: int = 0,
          technical_blocked: bool = False) -> SimpleNamespace:
    technical = {}
    if status is not None:
        technical = {"status": status, "task_id": task_id}
    return SimpleNamespace(
        id="maintenance-1",
        kind="review_failed",
        summary="The reviewer result could not be validated.",
        recommendation="Inspect retained evidence before retrying.",
        source_keys=["memory-1"],
        evidence_ids=["review-1"],
        detail={"handoff_needed": True, "technical_blocked": technical_blocked,
                **({"generation": generation} if generation else {}),
                **({"technical_work": technical} if technical else {})},
        state="pending",
        version=1,
    )


class _Response:
    def __init__(self, payload: object, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def json(self) -> object:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _Client:
    def __init__(self, *, post_response: _Response | None = None, get_response: _Response | None = None,
                 schedule_response: _Response | None = None,
                 settings_response: _Response | None = None) -> None:
        self.post_response = post_response
        self.get_response = get_response
        self.schedule_response = schedule_response or _Response([{"schedule_id": "work_pickup", "enabled": True}])
        self.settings_response = settings_response or _Response({"allowed_types": None, "external_origins": None})
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []
        self.schedule_gets: list[str] = []
        self.settings_gets: list[str] = []

    async def __aenter__(self) -> _Client:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def post(self, url: str, *, json: dict) -> _Response:
        self.posts.append((url, json))
        assert self.post_response is not None
        return self.post_response

    async def get(self, url: str) -> _Response:
        if url.endswith("/autonomous/schedules"):
            self.schedule_gets.append(url)
            return self.schedule_response
        if url.endswith("/autonomous/settings"):
            self.settings_gets.append(url)
            return self.settings_response
        self.gets.append(url)
        assert self.get_response is not None
        return self.get_response


@pytest.mark.asyncio
async def test_project_api_url_uses_registered_root_with_pythonpath_safe_registry() -> None:
    from app.services.context_maintenance_tasks import _project_api_url

    with (
        patch(
            "app.core.project_roots.get_registered_project_roots",
            new=AsyncMock(return_value={"summitflow": "/registered/summitflow"}),
        ),
        patch(
            "app.workflows._heartbeat_project._read_project_api_url",
            return_value="http://registered/api",
        ) as read_url,
    ):
        result = await _project_api_url()

    assert result == "http://registered/api"
    read_url.assert_called_once_with("summitflow", root=Path("/registered/summitflow"))


@pytest.mark.asyncio
async def test_dispatch_freezes_safe_idempotent_request_and_keeps_item_pending() -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": "pending", "project_id": "agent-hub"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()) as event,
    ):
        result = await dispatch_technical_work(db, item, reason="Recover the retained technical failure")

    assert result["task_id"] == "task-42"
    assert item.state == "pending"
    work = item.detail["technical_work"]
    assert work["request"]["external_origin"] == "agent-hub-context-maintenance"
    assert work["request"]["external_request_key"] == item.id
    assert work["request"]["auto_dispatch"] is True
    assert work["request"]["execution_mode"] == "autonomous"
    assert work["request"]["title"] == "Context maintenance recovery: Review failed"
    assert "review-1" in work["request"]["references"]
    assert "source content:" not in str(work["request"])
    assert client.posts[0][0] == "http://summitflow/api/projects/agent-hub/tasks"
    assert event.await_count == 2
    assert db.commit.await_count == 2


@pytest.mark.asyncio
async def test_dispatch_flushes_task_id_before_secondary_observations() -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock(), flush=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": "pending", "project_id": "agent-hub"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await dispatch_technical_work(db, item, reason="Recover the retained technical failure")

    assert result["task_id"] == "task-42"
    assert item.detail["technical_work"]["task_id"] == "task-42"
    db.flush.assert_awaited_once()


@pytest.mark.asyncio
async def test_initial_dispatch_retains_pending_task_but_marks_disabled_permission() -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": "pending", "project_id": "agent-hub"}))
    disabled = _permission(allowed=False, reason="auto_exec_disabled")

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
        patch("app.services.context_maintenance_tasks.check_execution_permission", new=AsyncMock(return_value=disabled)),
    ):
        result = await dispatch_technical_work(db, item, reason="Queue the retained technical failure")

    assert result["status"] == "pending"
    assert result["task_id"] == "task-42"
    assert result["technical_blocked"] is True
    assert item.state == "pending"
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True
    assert item.detail["technical_work"]["task_owned"] is False
    assert item.detail["technical_work"]["execution_permission"] == {
        "allowed": False,
        "permission_tier": "full",
        "auto_exec_enabled": False,
        "in_time_window": True,
        "reason": "auto_exec_disabled",
    }


@pytest.mark.asyncio
async def test_initial_dispatch_retains_pending_task_but_marks_pickup_disabled() -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(
        post_response=_Response({"id": "task-42", "status": "pending", "project_id": "agent-hub"}),
        schedule_response=_Response([{"schedule_id": "work_pickup", "enabled": False}]),
    )

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await dispatch_technical_work(db, item, reason="Queue the retained technical failure")

    assert result["status"] == "pending"
    assert result["task_id"] == "task-42"
    assert result["technical_blocked"] is True
    assert item.detail["technical_work"]["task_owned"] is False
    assert item.detail["technical_work"]["pickup_schedule"] == {
        "available": True,
        "enabled": False,
        "reason": "work_pickup_disabled",
    }
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True


@pytest.mark.asyncio
async def test_reconcile_pickup_filter_blocks_unlisted_external_origin() -> None:
    item = _item(status="pending", task_id="task-42")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(
        get_response=_Response({"id": "task-42", "status": "pending"}),
        settings_response=_Response({"allowed_types": ["bug"], "external_origins": ["other-origin"]}),
    )
    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["blocked"] == 1
    assert client.settings_gets == ["http://summitflow/api/projects/agent-hub/autonomous/settings"]
    assert item.detail["technical_work"]["task_owned"] is False
    assert item.detail["technical_work"]["pickup_schedule"]["reason"] == "external_origin_not_allowed"
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True


@pytest.mark.asyncio
async def test_reconcile_permission_enabled_clears_only_execution_block() -> None:
    item = _item(status="pending", task_id="task-42", technical_blocked=True)
    item.detail["technical_work"].update({
        "task_owned": False,
        "execution_permission_blocked": True,
        "execution_permission": {
            "allowed": False,
            "permission_tier": "full",
            "auto_exec_enabled": False,
            "in_time_window": True,
            "reason": "auto_exec_disabled",
        },
    })
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({"id": "task-42", "status": "pending"}))
    permission = AsyncMock(side_effect=[
        _permission(allowed=False, reason="auto_exec_disabled"),
        _permission(allowed=True, reason="allowed"),
    ])

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
        patch("app.services.context_maintenance_tasks.check_execution_permission", new=permission),
    ):
        first = await reconcile_technical_work(db)
        second = await reconcile_technical_work(db)

    assert first["blocked"] == 1
    assert second["blocked"] == 0
    assert item.detail["technical_work"]["status"] == "pending"
    assert item.detail["technical_work"]["task_owned"] is True
    assert "execution_permission_blocked" not in item.detail["technical_work"]
    assert "execution_permission" not in item.detail["technical_work"]
    assert item.detail["technical_blocked"] is False
    assert item.detail["handoff_needed"] is False


@pytest.mark.asyncio
async def test_reconcile_pickup_enabled_clears_only_pickup_block() -> None:
    item = _item(status="pending", task_id="task-42", technical_blocked=True)
    item.detail["technical_work"].update({
        "task_owned": False,
        "pickup_schedule_blocked": True,
        "pickup_schedule": {"available": True, "enabled": False, "reason": "work_pickup_disabled"},
    })
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(
        get_response=_Response({"id": "task-42", "status": "pending"}),
        schedule_response=_Response([{"schedule_id": "work_pickup", "enabled": False}]),
    )
    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        first = await reconcile_technical_work(db)
        client.schedule_response = _Response([{"schedule_id": "work_pickup", "enabled": True}])
        second = await reconcile_technical_work(db)

    assert first["blocked"] == 1
    assert second["blocked"] == 0
    assert item.detail["technical_work"]["status"] == "pending"
    assert item.detail["technical_work"]["task_owned"] is True
    assert "pickup_schedule_blocked" not in item.detail["technical_work"]
    assert "pickup_schedule" not in item.detail["technical_work"]
    assert item.detail["technical_blocked"] is False
    assert item.detail["handoff_needed"] is False


@pytest.mark.asyncio
async def test_reconcile_pickup_status_read_failure_is_visible_as_blocked() -> None:
    item = _item(status="pending", task_id="task-42")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(
        get_response=_Response({"id": "task-42", "status": "pending"}),
        schedule_response=_Response({}, status_code=503),
    )
    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["blocked"] == 1
    assert item.detail["technical_work"]["task_owned"] is False
    assert item.detail["technical_work"]["pickup_schedule"]["reason"] == "summitflow_pickup_status_http_503"
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True


@pytest.mark.asyncio
async def test_reconcile_running_task_does_not_apply_startup_permission_gate() -> None:
    item = _item(status="running", task_id="task-42", technical_blocked=False)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({"id": "task-42", "status": "running"}))
    permission = AsyncMock(return_value=_permission(allowed=False, reason="auto_exec_disabled"))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
        patch("app.services.context_maintenance_tasks.check_execution_permission", new=permission),
    ):
        result = await reconcile_technical_work(db)

    assert result["blocked"] == 0
    assert permission.await_count == 0
    assert item.detail["technical_work"]["task_owned"] is True
    assert item.detail["technical_blocked"] is False


@pytest.mark.asyncio
async def test_dispatch_replays_frozen_body_after_lost_ack() -> None:
    item = _item(status="dispatch_pending")
    frozen = {"title": "Frozen", "external_origin": "agent-hub-context-maintenance", "external_request_key": item.id}
    item.detail["technical_work"]["request"] = frozen
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": "pending"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        await dispatch_technical_work(db, item, reason="A different reason must not rewrite the request")

    assert client.posts[0][1] == frozen
    assert item.detail["technical_work"]["request"] == frozen


@pytest.mark.parametrize("task_status", ["failed", "cancelled", "archived"])
@pytest.mark.asyncio
async def test_dispatch_terminal_post_is_blocked_and_visible(task_status: str) -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": task_status}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await dispatch_technical_work(db, item, reason="Observe the terminal technical failure")

    assert result["status"] == task_status
    assert item.detail["technical_work"]["status"] == task_status
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True


@pytest.mark.asyncio
async def test_dispatch_generation_changes_external_request_key() -> None:
    item = _item(generation=2)
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response({"id": "task-42", "status": "pending"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        await dispatch_technical_work(db, item, reason="Dispatch a new explicit generation")

    assert client.posts[0][1]["external_request_key"] == "maintenance-1:generation-2"


@pytest.mark.asyncio
async def test_reconcile_completed_task_requests_revalidation_without_resolving() -> None:
    item = _item(status="running", task_id="task-42")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({"id": "task-42", "status": "completed"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["completed"] == 1
    assert item.state == "pending"
    assert item.detail["technical_work"]["status"] == "completed_pending_revalidation"
    assert item.detail["handoff_needed"] is True


@pytest.mark.asyncio
async def test_reconcile_terminal_failure_is_visible_and_does_not_repost() -> None:
    item = _item(status="running", task_id="task-42")
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({"id": "task-42", "status": "failed"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["blocked"] == 1
    assert item.detail["technical_work"]["status"] == "failed"
    assert item.detail["technical_blocked"] is True
    assert item.detail["handoff_needed"] is True
    assert not client.posts


@pytest.mark.asyncio
async def test_reconcile_reobserves_failed_task_after_remote_resume() -> None:
    item = _item(status="failed", task_id="task-42", technical_blocked=True)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({"id": "task-42", "status": "running"}))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["inspected"] == 1
    assert client.gets == ["http://summitflow/api/projects/agent-hub/tasks/task-42"]
    assert item.detail["technical_work"]["status"] == "running"
    assert item.detail["technical_blocked"] is False


@pytest.mark.asyncio
async def test_reconcile_keeps_revalidation_block_for_unchanged_completed_task() -> None:
    item = _item(status="blocked", task_id="task-42", technical_blocked=True)
    item.detail["technical_work"]["receipt"] = {
        "id": "task-42",
        "status": "completed",
        "completed_at": "2026-09-19T12:00:00Z",
        "updated_at": "2026-09-19T12:00:00Z",
    }
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({
        "id": "task-42",
        "status": "completed",
        "completed_at": "2026-09-19T12:00:00Z",
        "updated_at": "2026-09-19T12:00:00Z",
    }))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["inspected"] == 1
    assert client.gets == ["http://summitflow/api/projects/agent-hub/tasks/task-42"]
    assert item.detail["technical_work"]["status"] == "blocked"
    assert item.detail["technical_blocked"] is True


@pytest.mark.asyncio
async def test_reconcile_changed_completed_receipt_allows_one_revalidation() -> None:
    item = _item(status="blocked", task_id="task-42", technical_blocked=True)
    item.detail["technical_work"]["receipt"] = {
        "id": "task-42",
        "status": "completed",
        "completed_at": "2026-09-19T12:00:00Z",
        "updated_at": "2026-09-19T12:00:00Z",
    }
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(scalars=lambda: [item])),
        commit=AsyncMock(),
    )
    client = _Client(get_response=_Response({
        "id": "task-42",
        "status": "completed",
        "completed_at": "2026-09-19T12:05:00Z",
        "updated_at": "2026-09-19T12:05:00Z",
    }))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await reconcile_technical_work(db)

    assert result["completed"] == 1
    assert item.detail["technical_work"]["status"] == "completed_pending_revalidation"
    assert item.detail["technical_blocked"] is False


@pytest.mark.asyncio
async def test_malformed_success_response_is_retryable_without_losing_frozen_request() -> None:
    item = _item()
    db = SimpleNamespace(commit=AsyncMock())
    client = _Client(post_response=_Response([]))

    with (
        patch("app.services.context_maintenance_tasks._project_api_url", new=AsyncMock(return_value="http://summitflow/api")),
        patch("app.services.context_maintenance_tasks.httpx.AsyncClient", return_value=client),
        patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()),
    ):
        result = await dispatch_technical_work(db, item, reason="Retry safely")

    assert result["status"] == "dispatch_pending"
    assert item.detail["technical_work"]["request"]["external_request_key"] == item.id


@pytest.mark.asyncio
async def test_completed_receipt_is_reclassified_for_revalidation_without_post() -> None:
    item = _item(status="completed", task_id="task-42")
    db = SimpleNamespace(commit=AsyncMock())

    with patch("app.services.context_maintenance_tasks.maintenance_event", new=AsyncMock()):
        result = await dispatch_technical_work(db, item, reason="Reconcile receipt")

    assert result["status"] == "completed_pending_revalidation"
    assert item.detail["handoff_needed"] is True
