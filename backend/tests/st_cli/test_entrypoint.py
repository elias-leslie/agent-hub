"""Owner package and trusted namespace dispatch regressions."""

from __future__ import annotations

import ast
import json
from pathlib import Path
from unittest.mock import patch

import agent_hub_st
import pytest
import typer
from agent_hub_st import __main__ as entrypoint
from agent_hub_st.completion import call_complete
from agent_hub_st.memory_api import agent_hub_request
from agent_hub_st.prompt_api import prompt_api
from st_sdk.runtime import describe_app

EXPECTED_NAMESPACES = {
    "agents",
    "automations",
    "complete",
    "mandates",
    "memory",
    "models",
    "native-sessions",
    "note",
    "prompt",
    "skills",
    "workflow",
}


def test_entrypoint_owns_only_the_reviewed_static_namespaces() -> None:
    assert set(entrypoint.OWNED_APPS) == EXPECTED_NAMESPACES


def test_entrypoint_consumes_fixed_namespace_before_sdk_dispatch() -> None:
    with patch.object(entrypoint, "run_app", return_value="ok") as run:
        result = entrypoint.main(["models", "list", "--json"])

    assert result == "ok"
    run.assert_called_once_with(entrypoint.OWNED_APPS["models"], "models", ["list", "--json"])


@pytest.mark.parametrize("args", [[], ["web"]])
def test_entrypoint_rejects_missing_or_unowned_namespaces(args: list[str]) -> None:
    with pytest.raises(typer.Exit) as exc_info:
        entrypoint.main(args)

    assert exc_info.value.exit_code == 2


def test_all_owned_apps_have_static_help_without_running_callbacks() -> None:
    descriptions = {
        namespace: describe_app(app, namespace)
        for namespace, app in entrypoint.OWNED_APPS.items()
    }

    assert all(description["help"][""] for description in descriptions.values())
    assert "list" in descriptions["models"]["help"]
    assert "save" in descriptions["memory"]["help"]
    assert "audit" in descriptions["skills"]["help"]


def test_shipped_agents_manifest_discovers_local_credential_commands() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "st-extensions/agents.json").read_text())
    assert manifest["id"] == "agent-hub.agents"
    for operation in ("enroll", "refresh", "refs", "run"):
        assert f"credentials {operation}" in manifest["help"]
        assert any(
            usage["surface"] == f"st.agents.credentials.{operation}"
            for usage in manifest["usage"]
        )


def test_shipped_workflow_manifest_lists_every_command_and_a_guide_command() -> None:
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "st-extensions/workflow.json").read_text())
    assert manifest["id"] == "agent-hub.workflow"
    for command in ("create", "get", "wait", "add-step", "revise", "remove-step", "cancel", "resume", "list"):
        assert command in manifest["help"]
    surfaces = {usage["surface"]: usage for usage in manifest["usage"]}
    assert surfaces["st.workflow"]["cmd"] == "st workflow guide"
    assert all(usage.get("on_demand") for usage in surfaces.values())


def test_shipped_models_manifest_matches_the_command_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regenerate st-extensions/models.json (describe_app at COLUMNS=80) whenever a command or its help changes."""
    monkeypatch.setenv("COLUMNS", "80")
    root = Path(__file__).resolve().parents[3]
    manifest = json.loads((root / "st-extensions/models.json").read_text())
    described = describe_app(entrypoint.OWNED_APPS["models"], "models")
    assert (manifest["id"], manifest["namespace"], manifest["version"]) == (
        "agent-hub.models", "models", agent_hub_st.__version__,
    )
    assert manifest["help"] == described["help"]
    assert manifest["usage"] == described["usage"]
    assert manifest["help_options"] == described["help_options"]
    assert "route" in manifest["help"]


def test_owner_package_has_no_reverse_summitflow_imports() -> None:
    package_root = Path(agent_hub_st.__file__).parent
    imported_roots: set[str] = set()
    for path in package_root.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                if path.name == "lab_credentials.py" and node.module == "app.cli.lab_credentials":
                    # Fixed local owner backend, loaded only by command execution.
                    assert [alias.name for alias in node.names] == ["run_lab_operation"]
                    continue
                if path.name == "remote_hosts.py" and node.module == "app.cli.remote_hosts":
                    # Same fixed local owner backend, loaded only by command execution.
                    assert [alias.name for alias in node.names] == ["run_remote_host_operation"]
                    continue
                if path.name == "native_sessions.py" and node.module == "app.services.session_ingestion.native_operator":
                    # The local owner command binds the fixed Agent Hub backend
                    # before loading its own authority. This is not an import of
                    # SummitFlow's private `app` package.
                    assert [alias.name for alias in node.names] == ["run_native_operator"]
                    continue
                imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint({"app", "cli"})


def test_public_helper_contract_is_versioned_and_importable() -> None:
    assert agent_hub_st.PUBLIC_HELPER_API_VERSION == 2
    assert agent_hub_st.__version__ == "0.5.0"
    assert all(
        callable(helper)
        for helper in (
            call_complete,
            agent_hub_request,
            prompt_api,
        )
    )
