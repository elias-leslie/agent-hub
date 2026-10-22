"""Synthetic-only checks run with --confcutdir=tests/lab_credentials.

That flag excludes the repository conftest before fixtures run. The guards below
cover fixture-time env opens; they cannot protect imports in a parent conftest.
Use the real encryption helper with a disposable key and no configuration reads.
"""

from __future__ import annotations

import builtins
import importlib
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from cryptography.fernet import Fernet


@pytest.fixture(autouse=True)
def synthetic_settings(monkeypatch):
    original_open = Path.open
    original_builtin_open = builtins.open

    def env_path(path):
        return isinstance(path, (str, Path)) and (
            Path(path).name == ".env" or Path(path).name.startswith(".env.")
        )

    def guarded_open(path, *args, **kwargs):
        if env_path(path):
            raise AssertionError("Credential tests must not open env files")
        return original_open(path, *args, **kwargs)

    def guarded_builtin_open(path, *args, **kwargs):
        if env_path(path):
            raise AssertionError("Credential tests must not open env files")
        return original_builtin_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    monkeypatch.setattr(builtins, "open", guarded_builtin_open)
    settings = SimpleNamespace(agent_hub_encryption_key=Fernet.generate_key().decode())
    if "app.config" not in sys.modules:
        config = ModuleType("app.config")
        config.__dict__["settings"] = settings
        monkeypatch.setitem(sys.modules, "app.config", config)
    crypto = importlib.import_module("app.storage.credentials")
    monkeypatch.setattr(crypto, "settings", settings)
    yield crypto
