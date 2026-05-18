"""Tests for the lease-check permission hook."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from app.services.tools._lease_check_hook import create_lease_check_hook
from app.services.tools.base import ToolCall, ToolDecision


@pytest.fixture
def project_id(tmp_path):
    """Register a fake project root under KNOWN_ROOTS for the duration of a test."""
    pid = "test-lease-project"
    root = tmp_path / "project"
    root.mkdir()

    with patch(
        "app.constants.projects.get_known_roots",
        return_value={pid: str(root)},
    ):
        yield pid, root


class _FakeProc:
    def __init__(self, returncode: int, stderr: bytes = b""):
        self.returncode = returncode
        self._stderr = stderr
        self.killed = False

    async def communicate(self):
        return b"", self._stderr

    def kill(self):
        self.killed = True


async def _exec_factory(returncode: int, stderr: bytes = b""):
    fake = _FakeProc(returncode, stderr)

    async def _fake_exec(*args, **kwargs):
        return fake

    return fake, _fake_exec


@pytest.mark.asyncio
async def test_lease_check_allows_when_no_holder(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    _, fake_exec = await _exec_factory(0)
    with patch("shutil.which", return_value="/usr/bin/st"), \
         patch("app.services.tools._lease_check_hook.create_process", side_effect=fake_exec):
        decision = await hook(ToolCall(
            id="1", name="write_file",
            input={"file_path": str(root / "app.py")},
        ))

    assert decision == ToolDecision.ALLOW


@pytest.mark.asyncio
async def test_lease_check_denies_when_held(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    _, fake_exec = await _exec_factory(2, stderr=b"BLOCKED: app.py held by cc:abc123")
    with patch("shutil.which", return_value="/usr/bin/st"), \
         patch("app.services.tools._lease_check_hook.create_process", side_effect=fake_exec):
        decision = await hook(ToolCall(
            id="2", name="write_file",
            input={"file_path": str(root / "app.py")},
        ))

    assert decision == ToolDecision.DENY


@pytest.mark.asyncio
async def test_lease_check_skips_bash(project_id):
    pid, _ = project_id
    hook = create_lease_check_hook(pid)

    with patch("app.services.tools._lease_check_hook.create_process") as spawn:
        decision = await hook(ToolCall(
            id="3", name="bash",
            input={"command": "rm -rf /"},
        ))

    assert decision == ToolDecision.ALLOW
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_lease_check_skips_read_file(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    with patch("app.services.tools._lease_check_hook.create_process") as spawn:
        decision = await hook(ToolCall(
            id="4", name="read_file",
            input={"path": str(root / "app.py")},
        ))

    assert decision == ToolDecision.ALLOW
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_lease_check_allows_when_st_missing(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    with patch("shutil.which", return_value=None), \
         patch("app.services.tools._lease_check_hook.create_process") as spawn:
        decision = await hook(ToolCall(
            id="5", name="write_file",
            input={"file_path": str(root / "app.py")},
        ))

    assert decision == ToolDecision.ALLOW
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_lease_check_allows_on_timeout(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    class _HangingProc:
        returncode = None

        async def communicate(self):
            await asyncio.sleep(10)

        def kill(self):
            pass

    async def _fake_exec(*args, **kwargs):
        return _HangingProc()

    with patch("shutil.which", return_value="/usr/bin/st"), \
         patch("app.services.tools._lease_check_hook.create_process", side_effect=_fake_exec), \
         patch(
             "app.services.tools._lease_check_hook._LEASE_CHECK_TIMEOUT_SECONDS",
             0.05,
         ):
        decision = await hook(ToolCall(
            id="6", name="write_file",
            input={"file_path": str(root / "app.py")},
        ))

    assert decision == ToolDecision.ALLOW


@pytest.mark.asyncio
async def test_lease_check_allows_when_no_known_root():
    """Unregistered project_id falls through to ALLOW."""
    hook = create_lease_check_hook("never-registered-project")

    with patch("app.services.tools._lease_check_hook.create_process") as spawn:
        decision = await hook(ToolCall(
            id="7", name="write_file",
            input={"file_path": "/tmp/never-registered-project/app.py"},
        ))

    assert decision == ToolDecision.ALLOW
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_lease_check_empty_path_allowed(project_id):
    pid, _ = project_id
    hook = create_lease_check_hook(pid)

    with patch("app.services.tools._lease_check_hook.create_process") as spawn:
        decision = await hook(ToolCall(
            id="8", name="write_file",
            input={"file_path": ""},
        ))

    assert decision == ToolDecision.ALLOW
    spawn.assert_not_called()


@pytest.mark.asyncio
async def test_lease_check_relative_path_resolves_against_root(project_id):
    pid, root = project_id
    hook = create_lease_check_hook(pid)

    captured = {}

    async def _fake_exec(*args, **kwargs):
        captured["args"] = args
        captured["working_dir"] = kwargs.get("working_dir")
        return _FakeProc(0)

    with patch("shutil.which", return_value="/usr/bin/st"), \
         patch("app.services.tools._lease_check_hook.create_process", side_effect=_fake_exec):
        await hook(ToolCall(
            id="9", name="write_file",
            input={"file_path": "app/main.py"},
        ))

    assert captured["working_dir"] == root
    assert str(root / "app/main.py") in captured["args"]
