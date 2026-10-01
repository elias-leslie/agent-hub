"""Explicit provider user-message correlation, independent of command identity."""

import hashlib
import json
from typing import Any

from jsonschema import Draft7Validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NativeObservationSource, NativeUserIdentity

from .app_server_observations import SUPPORTED_VERSIONS, protocol_contract
from .native_models import NativeObservation


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


async def correlate_snapshot_users(db: AsyncSession, source: NativeObservationSource, observation: NativeObservation) -> tuple[list[dict[str, Any]], str | None]:
    profile = source.registration.get("_protocol_profile_version", source.registration["provider_version"])
    if profile not in SUPPORTED_VERSIONS or protocol_contract(profile)[0] != source.registration["schema_fingerprint"]:
        return [], "unsupported_app_server_contract"
    payload = observation.payload
    method, thread = payload.get("method"), payload.get("thread")
    if method not in {"thread/read", "thread/resume", "thread/fork"} or not isinstance(thread, dict):
        return [], "unsupported_snapshot_shape"
    schema = protocol_contract(profile)[1]["ServerNotification"].schema
    if not isinstance(schema, dict):
        return [], "unsupported_snapshot_shape"
    validator = Draft7Validator({"$ref": "#/definitions/Thread", "definitions": schema["definitions"]})
    if not validator.is_valid(thread):
        return [], "unsupported_snapshot_shape"
    if thread["id"] != observation.thread_id or thread["id"] != source.session_id:
        return [], "snapshot_thread_mismatch"
    if observation.history_owner_thread_id not in (None, observation.thread_id):
        return [], "inherited_history"
    forked = method == "thread/fork" or thread.get("forkedFromId") is not None
    mappings = []
    for turn in thread["turns"]:
        for item in turn["items"]:
            if item.get("type") != "userMessage":
                continue
            client_id = item.get("clientId")
            if not isinstance(client_id, str) or not 0 < len(client_id) <= 512 or not isinstance(item.get("id"), str) or not 0 < len(item["id"]) <= 512:
                continue
            key = _digest(["codex-user", source.registration["namespace"], observation.thread_id, turn["id"], client_id])
            identity = await db.get(NativeUserIdentity, key)
            if forked and (identity is None or not identity.live_verified):
                continue
            durable = method == "thread/read" and observation.origin == "stored_snapshot"
            if identity is None:
                identity = NativeUserIdentity(id=key, session_id=source.session_id, namespace=source.registration["namespace"], thread_id=observation.thread_id, turn_id=turn["id"], client_id=client_id, durable_item_id=item["id"] if durable else None, live_verified=False, aliases=[], projection_event_ids=[])
                db.add(identity)
            elif durable and identity.durable_item_id not in (None, item["id"]):
                return mappings, "native_user_identity_conflict"
            if durable:
                identity.durable_item_id = item["id"]
            alias = {"item_id": item["id"], "source_id": source.id, "position": observation.position, "origin": observation.origin, "evidence": "provider_user_message_client_id"}
            if not any(all(existing.get(key) == alias[key] for key in ("item_id", "source_id", "origin")) for existing in identity.aliases):
                identity.aliases = [*identity.aliases, alias]
            mappings.append({"user_entity_id": key, "thread_id": observation.thread_id, "turn_id": turn["id"], "item_id": item["id"], "canonical_item_id": identity.durable_item_id, "correlation": "explicit_provider_client_id", "projection_event_ids": identity.projection_event_ids})
    await db.flush()
    return mappings, None if mappings else "inherited_history" if forked else "snapshot_identity_unverified"


async def correlate_live_user(db: AsyncSession, source: NativeObservationSource, observation: NativeObservation) -> tuple[list[dict[str, Any]], str | None]:
    item = observation.payload.get("item", {})
    client_id = item.get("clientId")
    if observation.origin != "live" or not observation.turn_id or not observation.item_id or not isinstance(client_id, str) or not 0 < len(client_id) <= 512:
        return [], "missing_explicit_user_correlation"
    key = _digest(["codex-user", source.registration["namespace"], observation.thread_id, observation.turn_id, client_id])
    identity = await db.get(NativeUserIdentity, key)
    if identity and identity.durable_item_id not in (None, observation.item_id):
        return [], "native_user_identity_conflict"
    if identity is None:
        identity = NativeUserIdentity(id=key, session_id=source.session_id, namespace=source.registration["namespace"], thread_id=observation.thread_id, turn_id=observation.turn_id, client_id=client_id, durable_item_id=observation.item_id, live_verified=True, aliases=[], projection_event_ids=[])
        db.add(identity)
    identity.durable_item_id, identity.live_verified = observation.item_id, True
    alias = {"item_id": observation.item_id, "source_id": source.id, "position": observation.position, "origin": observation.origin, "evidence": "provider_user_message_client_id"}
    if not any(all(existing.get(field) == alias[field] for field in ("item_id", "source_id", "origin")) for existing in identity.aliases):
        identity.aliases = [*identity.aliases, alias]
    await db.flush()
    return [{"user_entity_id": key, "thread_id": observation.thread_id, "turn_id": observation.turn_id, "item_id": observation.item_id, "canonical_item_id": identity.durable_item_id, "correlation": "explicit_provider_client_id", "projection_event_ids": identity.projection_event_ids}], None
