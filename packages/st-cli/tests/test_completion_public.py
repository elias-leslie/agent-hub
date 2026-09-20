from __future__ import annotations

import io
from pathlib import Path

import pytest
import typer

from agent_hub_st import complete
from agent_hub_st.completion import completion_failed, resolve_message


def test_complete_compatibility_aliases_are_public_helpers() -> None:
    assert complete._resolve_message is resolve_message
    assert complete._completion_failed is completion_failed


@pytest.mark.parametrize(
    ("result", "failed"),
    [
        ({"content": "ok"}, False),
        ({"content": "Error: unavailable"}, True),
        ({"error": "unavailable", "content": "ok"}, True),
    ],
)
def test_completion_failed_preserves_response_contract(
    result: dict[str, object], failed: bool
) -> None:
    assert completion_failed(result) is failed


def test_resolve_message_preserves_input_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    message_file = tmp_path / "message.txt"
    message_file.write_text("from file")
    monkeypatch.setattr("sys.stdin", io.StringIO("from stdin"))

    assert resolve_message("argument", str(message_file)) == "argument"
    assert resolve_message(None, str(message_file)) == "from file"
    assert resolve_message(None, None) == "from stdin"


def test_resolve_message_missing_file_exits() -> None:
    with pytest.raises(typer.Exit) as exc_info:
        resolve_message(None, "/definitely/missing/completion-message.txt")

    assert exc_info.value.exit_code == 1
