"""Interpret pinned App Server wire evidence inside Agent Hub, never in collectors."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from .native_models import NativeObservation

SUPPORTED_VERSION = "codex-cli 0.159.3"
SUPPORTED_VERSIONS = ("codex-cli 0.159.2", SUPPORTED_VERSION)
PROTOCOL_ROOT = Path(__file__).with_name("codex_protocol")


@lru_cache
def protocol_contract(provider_version: str = SUPPORTED_VERSION) -> tuple[str, dict[str, Draft7Validator]]:
    if provider_version not in SUPPORTED_VERSIONS:
        raise ValueError("Unsupported Codex protocol profile")
    root = PROTOCOL_ROOT / provider_version.removeprefix("codex-cli ")
    schemas = {name: json.loads((root / f"{name}.json").read_text()) for name in ("ServerNotification", "ServerRequest")}
    fingerprint = hashlib.sha256(json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return fingerprint, {name: Draft7Validator(schema) for name, schema in schemas.items()}


def interpret_wire(observation: NativeObservation, registration: dict[str, Any]) -> tuple[NativeObservation, str | None]:
    """Return a derived view for reconciliation; the receipt retains the exact envelope."""
    if observation.kind != "app_server_event":
        return observation, None
    profile_version = registration.get("_protocol_profile_version", registration["provider_version"])
    if profile_version not in SUPPORTED_VERSIONS:
        return observation, "unsupported_app_server_contract"
    fingerprint, validators = protocol_contract(profile_version)
    if registration["schema_fingerprint"] != fingerprint:
        return observation, "unsupported_app_server_contract"
    wire = observation.payload
    schema = "ServerRequest" if "id" in wire else "ServerNotification"
    if not validators[schema].is_valid(wire):
        return observation, "unsupported_app_server_shape"
    params = wire["params"]
    thread = params.get("thread", {})
    own = params.get("threadId") or thread.get("id")
    if own != observation.thread_id:
        return observation, "app_server_thread_mismatch"
    turn = params.get("turnId") or params.get("turn", {}).get("id")
    item = params.get("item", {})
    item_id = params.get("itemId") or item.get("id")
    # Collector metadata is never allowed to change the wire's native subject.
    if observation.turn_id not in (None, turn) or observation.item_id not in (None, item_id):
        return observation, "app_server_subject_mismatch"
    kind = "lifecycle"
    quality = "unknown"
    if wire["method"] in {"item/started", "item/completed"} and item.get("type") == "commandExecution":
        kind = "command_execution"
        # Validated live execution notifications carry the provider item subject.
        # Read/resume snapshots do not. ID spelling, content and collector quality
        # claims never determine whether an observation is a live execution.
        quality = "durable" if observation.origin == "live" else "provisional"
    elif wire["method"] in {"item/started", "item/completed"} and item.get("type") == "userMessage":
        kind = "user_message"
        quality = "durable" if observation.origin == "live" else "provisional"
    elif wire["method"].endswith("/requestApproval"):
        kind = "approval_request"
    elif wire["method"] == "serverRequest/resolved":
        kind = "approval_resolution"
    elif wire["method"] == "thread/tokenUsage/updated":
        kind = "usage_snapshot"
    return observation.model_copy(update={"kind": kind, "turn_id": turn, "item_id": item_id, "identity_quality": quality, "payload": params, "source_reference": {**observation.source_reference, "wire_method": wire["method"], **({"request_id": wire["id"]} if "id" in wire else {})}}), None
