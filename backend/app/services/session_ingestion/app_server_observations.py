"""Interpret pinned App Server wire evidence inside Agent Hub, never in collectors."""

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft7Validator

from .native_models import NativeObservation

SUPPORTED_VERSION = "codex-cli 0.159.2"
PROTOCOL_ROOT = Path(__file__).with_name("codex_protocol")


@lru_cache
def protocol_contract() -> tuple[str, dict[str, Draft7Validator]]:
    schemas = {name: json.loads((PROTOCOL_ROOT / f"{name}.json").read_text()) for name in ("ServerNotification", "ServerRequest")}
    fingerprint = hashlib.sha256(json.dumps(schemas, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return fingerprint, {name: Draft7Validator(schema) for name, schema in schemas.items()}


def interpret_wire(observation: NativeObservation, registration: dict[str, Any]) -> tuple[NativeObservation, str | None]:
    """Return a derived view for reconciliation; the receipt retains the exact envelope."""
    if observation.kind != "app_server_event":
        return observation, None
    fingerprint, validators = protocol_contract()
    if registration["provider_version"] != SUPPORTED_VERSION or registration["schema_fingerprint"] != fingerprint:
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
        # Native live command IDs are durable in the pinned protocol. Snapshot
        # identities are never upgraded by spelling, content or collector claims.
        quality = "durable" if observation.origin == "live" and not str(item_id).startswith("item-") else "provisional"
    elif wire["method"].endswith("/requestApproval"):
        kind = "approval_request"
    elif wire["method"] == "serverRequest/resolved":
        kind = "approval_resolution"
    elif wire["method"] == "thread/tokenUsage/updated":
        kind = "usage_snapshot"
    return observation.model_copy(update={"kind": kind, "turn_id": turn, "item_id": item_id, "identity_quality": quality, "payload": params}), None
