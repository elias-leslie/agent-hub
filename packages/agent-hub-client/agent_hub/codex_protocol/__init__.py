"""Versioned transport conformance assets; normalization belongs to Agent Hub."""

import hashlib
import json
from importlib.resources import files

SUPPORTED_VERSION = "codex-cli 0.159.3"
SUPPORTED_VERSIONS = ("codex-cli 0.159.2", SUPPORTED_VERSION)


def schemas(provider_version: str = SUPPORTED_VERSION) -> dict[str, dict]:
    if provider_version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported Codex protocol profile")
    root = files(__package__).joinpath(provider_version.removeprefix("codex-cli "))
    return {name: json.loads(root.joinpath(f"{name}.json").read_text()) for name in ("ServerNotification", "ServerRequest")}


def fingerprint(provider_version: str = SUPPORTED_VERSION) -> str:
    return hashlib.sha256(json.dumps(schemas(provider_version), sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def profile(provider_version: str = SUPPORTED_VERSION) -> dict[str, str]:
    return {"provider_version": provider_version, "schema_fingerprint": fingerprint(provider_version)}
