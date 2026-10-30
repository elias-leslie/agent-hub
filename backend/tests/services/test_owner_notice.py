"""Owner notices: real payloads validate against Nightshift's contract; failures alert, the next success resolves."""

import json
import shutil
import subprocess
from unittest.mock import AsyncMock, patch

import pytest

from app.services import owner_notice

pytestmark = pytest.mark.skipif(shutil.which("nightshift") is None, reason="nightshift not on PATH")


def _validates(notice: dict) -> None:
    result = subprocess.run(
        ["nightshift", "push", "--json", "--dry-run"], input=json.dumps(notice),
        capture_output=True, text=True, timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert notice["actions"][0] == notice["primary"]


def test_job_failed_notice_matches_the_contract():
    notice = owner_notice.job_failed_notice("session_cleanup", "run-1")
    _validates(notice)
    assert notice["key"] == "agent-hub-job-session_cleanup"
    assert notice["push"] == "tray"


def test_retention_archive_notice_matches_the_contract():
    _validates(owner_notice.retention_archive_notice([f"s{i}" for i in range(9)]))


@pytest.mark.asyncio
async def test_failed_run_sends_and_successful_run_after_failure_resolves():
    with (
        patch.object(owner_notice, "send_notice", new=AsyncMock()) as send,
        patch.object(owner_notice, "resolve_notice", new=AsyncMock()) as resolve,
        patch.object(owner_notice, "_previous_run_failed", new=AsyncMock(return_value=True)),
    ):
        await owner_notice.notify_run_settled("run-1", "agent-hub.data_retention", "failed")
        send.assert_awaited_once()
        assert send.call_args_list[0].args[0]["key"] == "agent-hub-job-data_retention"
        await owner_notice.notify_run_settled("run-2", "agent-hub.data_retention", "succeeded")
        resolve.assert_awaited_once()
        assert resolve.call_args_list[0].args[0] == "agent-hub-job-data_retention"


@pytest.mark.asyncio
async def test_other_projects_runs_cancelled_runs_and_clean_successes_stay_quiet():
    with (
        patch.object(owner_notice, "send_notice", new=AsyncMock()) as send,
        patch.object(owner_notice, "resolve_notice", new=AsyncMock()) as resolve,
        patch.object(owner_notice, "_previous_run_failed", new=AsyncMock(return_value=False)),
    ):
        await owner_notice.notify_run_settled("r", "summitflow.browser_workflow", "failed")
        await owner_notice.notify_run_settled("r", "agent-hub.session_cleanup", "cancelled")
        await owner_notice.notify_run_settled("r", "agent-hub.session_cleanup", "succeeded")
    send.assert_not_awaited()
    resolve.assert_not_awaited()


@pytest.mark.asyncio
async def test_retention_failures_alert_and_a_clean_run_resolves():
    with (
        patch.object(owner_notice, "send_notice", new=AsyncMock()) as send,
        patch.object(owner_notice, "resolve_notice", new=AsyncMock()) as resolve,
    ):
        await owner_notice.notify_retention_result(["s1"])
        send.assert_awaited_once()
        await owner_notice.notify_retention_result([])
        resolve.assert_awaited_once()
        assert resolve.call_args_list[0].args[0] == owner_notice.RETENTION_ARCHIVE_KEY


@pytest.mark.asyncio
async def test_missing_nightshift_never_raises():
    with patch.object(owner_notice, "_nightshift", return_value=None):
        assert await owner_notice.send_notice(owner_notice.job_failed_notice("x", "r")) is False
