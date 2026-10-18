from __future__ import annotations

import importlib
import sys
from pathlib import Path

SCRIPTS_LIB = Path(__file__).resolve().parents[3] / "scripts" / "lib"
if str(SCRIPTS_LIB) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_LIB))

codex_sync_credentials = importlib.import_module("codex_sync_credentials")


def test_load_env_credentials_requires_only_registered_client_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text(
        'SUMMITFLOW_CLIENT_ID="summitflow"\n'
        "SUMMITFLOW_CLIENT_SECRET=obsolete-and-ignored\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(codex_sync_credentials, "ENV_FILE", env_file)

    assert codex_sync_credentials.load_env_credentials() == "summitflow"


def test_load_env_credentials_returns_empty_without_client_id(
    tmp_path: Path,
    monkeypatch,
) -> None:
    env_file = tmp_path / ".env.local"
    env_file.write_text("SUMMITFLOW_CLIENT_SECRET=obsolete\n", encoding="utf-8")
    monkeypatch.setattr(codex_sync_credentials, "ENV_FILE", env_file)

    assert codex_sync_credentials.load_env_credentials() == ""
