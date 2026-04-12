from __future__ import annotations

import json
from unittest.mock import patch

from app.api.complete.tool_provisioner import provision_standard_tools


class _DummyRedis:
    def __init__(self, payload: dict[str, object] | None) -> None:
        self._payload = payload

    def get(self, _key: str) -> str | None:
        if self._payload is None:
            return None
        return json.dumps(self._payload)

    def close(self) -> None:
        return None


def test_provision_standard_tools_uses_minimal_shell_first_baseline() -> None:
    result = provision_standard_tools(True, None)

    assert [tool["name"] for tool in result.loaded_tools] == [
        "bash",
        "read_file",
        "write_file",
    ]


def test_persona_read_tier_hides_runtime_denied_operational_tools() -> None:
    with patch("redis.from_url", return_value=_DummyRedis({"tier": "read"})):
        result = provision_standard_tools(
            True,
            None,
            agent_slug="persona",
            project_id="agent-hub",
        )

    names = {tool["name"] for tool in result.loaded_tools}
    assert "manage_tasks" not in names
    assert "dispatch_agent" not in names
    assert "send_push" in names
    assert "query_sessions" in names


def test_persona_yolo_tier_keeps_manage_and_dispatch_visible() -> None:
    with patch("redis.from_url", return_value=_DummyRedis({"tier": "yolo"})):
        result = provision_standard_tools(
            True,
            None,
            agent_slug="persona",
            project_id="agent-hub",
        )

    names = {tool["name"] for tool in result.loaded_tools}
    assert "manage_tasks" in names
    assert "dispatch_agent" in names
