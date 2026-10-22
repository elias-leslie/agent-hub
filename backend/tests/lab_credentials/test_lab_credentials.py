"""Scoped source, expiry and provider separation with no services or real secrets."""

from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models import Credential
from app.storage.lab_credentials import (
    LabCredentialError,
    LabCredentialRequest,
    prepare_lab_credential,
    resolve_lab_credentials,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)
REF = "secret://lab/example-local/viewer"


def database(rows):
    db = MagicMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = rows
    db.execute = AsyncMock(return_value=result)
    return db


def row(reference=REF, **kwargs):
    return prepare_lab_credential(
        reference, {"username": "test-viewer", "password": "synthetic-only-value"},
        kind="synthetic", now=NOW, **kwargs,
    )


@pytest.mark.asyncio
async def test_roundtrip_only_returns_requested_fields_without_persisting():
    credential = row()
    assert b"synthetic-only-value" not in credential.value_encrypted
    db = database([credential])
    result = await resolve_lab_credentials(
        db, "example-local", [LabCredentialRequest(REF, ("password",))], now=NOW,
    )
    assert result[0].values == {"password": "synthetic-only-value"}
    assert "synthetic-only-value" not in repr(result)
    assert "test-viewer" not in repr(result)
    db.add.assert_not_called()
    db.commit.assert_not_called()
    params = db.execute.call_args.args[0].compile().params
    assert "_lab_example-local" in params.values()
    assert ["viewer"] in params.values()


@pytest.mark.parametrize("reference", [
    "secret://lab/other-local/viewer", "secret://system/example-local/viewer",
    "secret://lab/example-local/viewer?token=value", "secret://lab/example-local/%76iewer",
    "secret://lab/example-local/../viewer", "file:///tmp/credentials",
])
@pytest.mark.asyncio
async def test_bad_or_cross_target_reference_stops_before_lookup(reference):
    db = database([])
    with pytest.raises(LabCredentialError):
        await resolve_lab_credentials(
            db, "example-local", [LabCredentialRequest(reference, ("password",))], now=NOW,
        )
    db.execute.assert_not_called()


@pytest.mark.parametrize("case", ["missing", "duplicate", "foreign", "provider"])
@pytest.mark.asyncio
async def test_missing_ambiguous_or_foreign_rows_stop_before_decryption(case, monkeypatch, synthetic_settings):
    credential = row()
    rows = {"missing": [], "duplicate": [credential, credential], "foreign": [row("secret://lab/other-local/viewer")],
            "provider": [Credential(provider="openai", credential_type="viewer", value_encrypted=b"unused")]}[case]
    decrypt = MagicMock(side_effect=AssertionError("must not decrypt"))
    monkeypatch.setattr(synthetic_settings, "decrypt_value", decrypt)
    with pytest.raises(LabCredentialError):
        await resolve_lab_credentials(database(rows), "example-local", [LabCredentialRequest(REF, ("password",))], now=NOW)
    decrypt.assert_not_called()


@pytest.mark.asyncio
async def test_two_actors_are_independent_and_request_order_is_preserved():
    admin_ref = "secret://lab/example-local/admin"
    admin = prepare_lab_credential(admin_ref, {"password": "synthetic-admin"}, kind="synthetic", now=NOW)
    result = await resolve_lab_credentials(database([admin, row()]), "example-local", [
        LabCredentialRequest(REF, ("username",)), LabCredentialRequest(admin_ref, ("password",)),
    ], now=NOW)
    assert [item.reference for item in result] == [REF, admin_ref]
    assert result[0].values == {"username": "test-viewer"}
    assert result[1].values == {"password": "synthetic-admin"}


@pytest.mark.parametrize("change", ["expired", "no-expiry", "wrong-identity", "real", "invalid-json", "missing-field", "broken-ciphertext", "invalid-version"])
@pytest.mark.asyncio
async def test_invalid_or_expired_payload_never_returns_values(change, synthetic_settings):
    credential = row()
    payload = json.loads(synthetic_settings.decrypt_value(credential.value_encrypted))
    if change == "expired":
        payload["expires_at"] = NOW.isoformat()
    elif change == "no-expiry":
        payload["kind"] = "temporary"
    elif change == "wrong-identity":
        payload["reference"] = "secret://lab/other-local/viewer"
    elif change == "real":
        payload["kind"] = "real"
    elif change == "missing-field":
        payload["values"].pop("password")
    elif change == "invalid-version":
        payload["schema_version"] = True
    credential.value_encrypted = synthetic_settings.encrypt_value(
        "synthetic-only-value" if change == "invalid-json" else json.dumps(payload),
    )
    if change == "broken-ciphertext":
        credential.value_encrypted = b"synthetic-only-value"
    with pytest.raises(LabCredentialError) as caught:
        await resolve_lab_credentials(database([credential]), "example-local", [LabCredentialRequest(REF, ("password",))], now=NOW)
    assert "synthetic-only-value" not in str(caught.value)


@pytest.mark.asyncio
async def test_temporary_expiry_and_empty_requests():
    credential = prepare_lab_credential(REF, {"password": "synthetic-temporary"}, kind="temporary",
                                        expires_at=NOW + timedelta(minutes=1), now=NOW)
    result = await resolve_lab_credentials(database([credential]), "example-local", [LabCredentialRequest(REF, ("password",))], now=NOW)
    assert result[0].values["password"] == "synthetic-temporary"
    db = database([])
    assert await resolve_lab_credentials(db, "example-local", [], now=NOW) == []
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_temporary_credential_expiring_during_lookup_is_rejected(monkeypatch):
    module = importlib.import_module("app.storage.lab_credentials")
    credential = prepare_lab_credential(
        REF, {"password": "synthetic-temporary"}, kind="temporary",
        expires_at=NOW + timedelta(seconds=1), now=NOW,
    )
    db = database([credential])
    result = await db.execute()

    class Clock(datetime):
        current = NOW

        @classmethod
        def now(cls, tz=None):
            return cls.current

    async def delayed_lookup(*args, **kwargs):
        Clock.current = NOW + timedelta(seconds=2)
        return result

    db.execute = AsyncMock(side_effect=delayed_lookup)
    monkeypatch.setattr(module, "datetime", Clock)
    with pytest.raises(LabCredentialError, match="expired"):
        await resolve_lab_credentials(db, "example-local", [LabCredentialRequest(REF, ("password",))])


def test_synthetic_fixture_rejects_builtin_env_reads(synthetic_settings):
    with pytest.raises(AssertionError, match="must not open env files"):
        open("synthetic/.env")  # noqa: SIM115 - the guard raises before a handle exists


@pytest.mark.parametrize("fields", [(), ("password", "password"), ("bad-field",)])
@pytest.mark.asyncio
async def test_invalid_field_request_stops_before_lookup(fields):
    db = database([])
    with pytest.raises(LabCredentialError):
        await resolve_lab_credentials(db, "example-local", [LabCredentialRequest(REF, fields)], now=NOW)
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_duplicate_actor_request_stops_before_lookup():
    db = database([])
    request = LabCredentialRequest(REF, ("password",))
    with pytest.raises(LabCredentialError):
        await resolve_lab_credentials(db, "example-local", [request, request], now=NOW)
    db.execute.assert_not_called()


def test_enrollment_rejects_ambiguous_kind_expiry_or_values():
    for kwargs in [dict(kind="real"), dict(kind="temporary"), dict(kind="synthetic", expires_at=NOW.replace(tzinfo=None))]:
        with pytest.raises(LabCredentialError):
            prepare_lab_credential(REF, {"password": "synthetic-only-value"}, now=NOW, **kwargs)
    with pytest.raises(LabCredentialError):
        prepare_lab_credential(REF, {"password": ""}, kind="synthetic", now=NOW)


@pytest.mark.asyncio
async def test_provider_cache_never_decrypts_lab_rows(monkeypatch):
    module = importlib.import_module("app.services.credential_manager")
    module.CredentialManager.reset()
    manager = module.CredentialManager()
    decrypt = MagicMock(return_value="synthetic-provider-key")
    monkeypatch.setattr(module, "decrypt_value", decrypt)
    lab = row()
    provider = Credential(id=2, provider="openai", credential_type="api_key", value_encrypted=b"provider-test")
    assert await manager.load(database([lab, provider])) == 1
    decrypt.assert_called_once_with(b"provider-test")
    assert manager.list_providers() == ["openai"]
    for action in [lambda: manager.set("_lab_example-local", "viewer", "value"),
                   lambda: manager.set_api_keys("_lab_example-local", ["value"]),
                   lambda: manager.replace_value("_lab_example-local", "viewer", "old", "value")]:
        with pytest.raises(ValueError):
            action()
    module.CredentialManager.reset()


@pytest.mark.asyncio
async def test_general_credential_api_never_decrypts_or_updates_lab_rows(monkeypatch):
    module = importlib.import_module("app.api.credentials")
    credential = row()
    credential.id = 4
    db = database([credential])
    db.get = AsyncMock(return_value=credential)
    decrypt = MagicMock(side_effect=AssertionError("must not decrypt lab row"))
    monkeypatch.setattr(module, "decrypt_value", decrypt)
    assert await module.list_credentials(db, provider=None) == {"credentials": [], "total": 0}
    for action in [lambda: module.get_credential(4, db),
                   lambda: module.update_credential(4, module.CredentialUpdate(value="synthetic-replacement"), db),
                   lambda: module.set_primary_credential(4, db),
                   lambda: module.delete_credential(4, db)]:
        with pytest.raises(HTTPException) as caught:
            await action()
        assert caught.value.status_code == 404
    decrypt.assert_not_called()
    db.commit.assert_not_called()
