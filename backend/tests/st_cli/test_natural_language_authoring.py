"""Authoring must preserve factual prose and uncertainty across CLI entry points."""

from unittest.mock import patch

from agent_hub_st.memory import app as memory_app
from agent_hub_st.prompt import app as prompt_app
from typer.testing import CliRunner

CONTENT = "A timeout could indicate packet loss.\n\n- For example, compare a successful request."


def test_prompt_create_accepts_natural_prose(tmp_path):
    path = tmp_path / "prompt.md"
    path.write_text(CONTENT)
    with patch("agent_hub_st.prompt.prompt_api", return_value={"slug": "network-evidence"}) as api:
        result = CliRunner().invoke(prompt_app, ["create", "network-evidence", "Network evidence", "--file", str(path)])
    assert result.exit_code == 0, result.output
    assert api.call_args.kwargs["json"]["content"] == CONTENT


def test_memory_save_accepts_facts_and_markdown():
    with patch("agent_hub_st.memory.save_impl") as save:
        result = CliRunner().invoke(memory_app, ["save", CONTENT, "--summary", "Network timeout evidence"])
    assert result.exit_code == 0, result.output
    assert save.call_args.args[1] == CONTENT
