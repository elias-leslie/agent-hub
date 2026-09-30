"""Pinned transport conformance assets. This package performs no normalization."""

import hashlib
import json
from importlib.resources import files

SUPPORTED_VERSION = "codex-cli 0.159.2"


def schemas() -> dict[str, dict]:
    return {name: json.loads(files(__package__).joinpath(f"{name}.json").read_text()) for name in ("ServerNotification", "ServerRequest")}


def fingerprint() -> str:
    return hashlib.sha256(json.dumps(schemas(), sort_keys=True, separators=(",", ":")).encode()).hexdigest()
