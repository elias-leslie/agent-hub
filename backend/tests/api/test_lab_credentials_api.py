"""Owner-only agent logins API: metadata out, values never out."""

import json
import os
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from cryptography.fernet import Fernet

from app.api.lab_credentials import normalize_totp
from app.core.access_identity import require_owner
from app.db import get_db
from app.main import app
from app.storage import lab_credentials as storage
from tests.conftest import APITestClient

TEST_KEY = Fernet.generate_key().decode()
SECRET = "JBSWY3DPEHPK3PXP"


class FakeTable:
    """The credentials table: answers the storage module's selects from its rows."""

    def __init__(self, rows):
        self.rows = rows
        self.locks = 0
        self.db = MagicMock()
        self.db.begin.side_effect = self._begin
        self.db.execute = AsyncMock(side_effect=self._execute)
        self.db.add = MagicMock(side_effect=self._add)
        self.db.delete = AsyncMock(side_effect=self.rows.remove)
        self.db.flush = AsyncMock()

    @asynccontextmanager
    async def _begin(self):
        yield

    def _add(self, row):
        row.created_at = row.updated_at = datetime.now(UTC)
        self.rows.append(row)

    async def _execute(self, statement):
        if not hasattr(statement, "whereclause"):  # the LOCK TABLE text clause
            self.locks += 1
            return MagicMock()
        params = statement.compile().params
        actor = params.get("credential_type_1")
        provider = params.get("provider_1")
        rows = [
            row for row in self.rows
            if (actor is None or row.credential_type == actor)
            and (provider is None or actor is None or row.provider == provider)
            and row.provider.startswith("_lab_")
        ]
        return MagicMock(scalars=lambda: MagicMock(all=lambda: rows), all=lambda: rows)


def row(target, actor, kind, values, expires_at=None):
    reference = f"secret://lab/{target}/{actor}"
    credential = storage.prepare_lab_credential(
        reference, values, kind=kind, expires_at=expires_at,
        now=(expires_at - timedelta(days=2)) if expires_at else None,
    )
    credential.created_at = datetime(2026, 10, 1, tzinfo=UTC)
    credential.updated_at = datetime(2026, 10, 2, tzinfo=UTC)
    return credential


@pytest.fixture(autouse=True)
def encryption():
    with patch("app.storage.credentials.settings") as settings:
        settings.agent_hub_encryption_key = TEST_KEY
        yield


@pytest.fixture
def table():
    return FakeTable([])


@pytest.fixture
def client(table):
    async def override_get_db():
        yield table.db

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_owner] = lambda: None  # owner gate: test_owner_gates.py
    yield APITestClient(app)
    app.dependency_overrides.clear()


def generated():
    return {"username": "owner-" + os.urandom(4).hex(), "password": os.urandom(12).hex()}


def test_list_returns_metadata_and_login_url_but_never_values(client, table):
    account = {**generated(), "totp_secret": SECRET, "login_url": "https://hackerone.com/users/sign_in"}
    synthetic = {"password": os.urandom(12).hex(), "session_cookie": os.urandom(12).hex()}
    future = datetime.now(UTC) + timedelta(days=3)
    past = datetime.now(UTC) - timedelta(hours=1)
    table.rows += [
        row("hackerone", "default", "account", account),
        row("neri-local", "viewer", "synthetic", synthetic),
        row("neri-local", "temp", "temporary", {"password": "x"}, expires_at=future),
        row("neri-local", "old", "synthetic", {"password": "y"}, expires_at=past + timedelta(seconds=1)),
    ]
    table.rows[3].value_encrypted = storage.prepare_lab_credential(
        "secret://lab/neri-local/old", {"password": "y"}, kind="synthetic",
        expires_at=past, now=past - timedelta(days=1),
    ).value_encrypted

    response = client.get("/api/lab-credentials")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 4
    by_ref = {item["reference"]: item for item in body["credentials"]}
    hackerone = by_ref["secret://lab/hackerone/default"]
    assert hackerone["target"] == "hackerone" and hackerone["actor"] == "default"
    assert hackerone["kind"] == "account"
    assert hackerone["fields"] == ["login_url", "password", "totp_secret", "username"]
    assert hackerone["login_url"] == "https://hackerone.com/users/sign_in"
    assert hackerone["expires_at"] is None and hackerone["expired"] is False
    assert hackerone["undecodable"] is False
    assert hackerone["created_at"].startswith("2026-10-01") and hackerone["updated_at"].startswith("2026-10-02")
    assert by_ref["secret://lab/neri-local/viewer"]["login_url"] is None
    assert by_ref["secret://lab/neri-local/temp"]["kind"] == "temporary"
    assert by_ref["secret://lab/neri-local/temp"]["expired"] is False
    assert by_ref["secret://lab/neri-local/old"]["expired"] is True
    for value in (*account.values(), *synthetic.values()):
        if value != account["login_url"]:
            assert value not in response.text


def test_list_flags_an_undecodable_row_without_failing(client, table):
    broken = row("neri-local", "broken", "synthetic", {"password": "x"})
    broken.value_encrypted = b"not a token"
    table.rows += [broken, row("neri-local", "viewer", "synthetic", {"password": "x"})]

    items = client.get("/api/lab-credentials").json()["credentials"]

    flagged = next(item for item in items if item["actor"] == "broken")
    assert flagged["undecodable"] is True
    assert flagged["kind"] is None and flagged["fields"] == [] and flagged["login_url"] is None
    assert next(item for item in items if item["actor"] == "viewer")["undecodable"] is False


def test_list_ignores_rows_outside_the_lab_namespace(client, table):
    other = row("neri-local", "viewer", "synthetic", {"password": "x"})
    other.provider = "claude"
    table.rows.append(other)
    assert client.get("/api/lab-credentials").json() == {"credentials": [], "total": 0}


def test_add_account_stores_a_bundle_the_adapter_can_read(client, table):
    values = generated()
    response = client.post("/api/lab-credentials", json={
        "target": "hackerone", **values, "login_url": "https://hackerone.com/users/sign_in",
        "totp_secret": f"otpauth://totp/H1:me?secret={SECRET.lower()}&issuer=H1",
    })

    assert response.status_code == 201
    assert response.json() == {"reference": "secret://lab/hackerone/default"}
    assert table.locks == 1
    for value in values.values():
        assert value not in response.text
    from app.storage.credentials import decrypt_value

    stored = json.loads(decrypt_value(table.rows[0].value_encrypted))
    assert table.rows[0].provider == "_lab_hackerone" and table.rows[0].credential_type == "default"
    assert stored["kind"] == "account" and stored["expires_at"] is None
    assert stored["values"] == {
        **values, "login_url": "https://hackerone.com/users/sign_in", "totp_secret": SECRET,
    }


def test_add_account_refuses_a_duplicate_and_bad_input_without_echoing_values(client, table):
    values = generated()
    payload = {"target": "hackerone", **values, "login_url": "https://hackerone.com/login"}
    assert client.post("/api/lab-credentials", json=payload).status_code == 201

    duplicate = client.post("/api/lab-credentials", json=payload)
    assert duplicate.status_code == 409

    bad = [
        {**payload, "actor": "Not Valid"},
        {**payload, "login_url": "http://example.com/login"},
        {**payload, "login_url": "javascript:alert(1)"},
        {**payload, "totp_secret": "not base32!"},
        {k: v for k, v in payload.items() if k != "password"},
        {**payload, "unexpected": "field"},
    ]
    for attempt in bad:
        response = client.post("/api/lab-credentials", json={**attempt, "target": "other"})
        assert response.status_code in (400, 422)
        for value in values.values():
            assert value not in response.text
    assert len(table.rows) == 1


@pytest.mark.parametrize("text", [
    SECRET,
    "jbsw y3dp-ehpk 3pxp==",
    f"otpauth://totp/Site:me?secret={SECRET}&issuer=Site&algorithm=sha1&digits=6&period=30",
])
def test_totp_input_normalises_to_base32(text):
    assert normalize_totp(text) == SECRET


@pytest.mark.parametrize("text", [
    f"otpauth://totp/x?secret={SECRET}&digits=8",
    f"otpauth://totp/x?secret={SECRET}&period=60",
    f"otpauth://totp/x?secret={SECRET}&algorithm=SHA256",
    f"otpauth://hotp/x?secret={SECRET}&counter=1",
    "otpauth://totp/x?issuer=nosecret",
    "0189!",
])
def test_totp_refuses_other_settings_and_bad_secrets(text):
    with pytest.raises(ValueError) as caught:
        normalize_totp(text)
    assert SECRET not in str(caught.value)


def test_replace_an_account_swaps_the_whole_bundle(client, table):
    table.rows.append(row("hackerone", "default", "account", {**generated(), "login_url": "https://old.example/"}))
    values = generated()

    response = client.put("/api/lab-credentials/hackerone/default", json={
        **values, "login_url": "https://hackerone.com/login",
    })

    assert response.status_code == 200
    from app.storage.credentials import decrypt_value

    stored = json.loads(decrypt_value(table.rows[0].value_encrypted))
    assert stored["kind"] == "account"
    assert stored["values"] == {**values, "login_url": "https://hackerone.com/login"}
    assert values["password"] not in response.text


def test_replace_a_synthetic_bundle_with_values_and_expiry(client, table):
    table.rows.append(row("neri-local", "viewer", "synthetic", {"password": "old"}))
    new = {"password": os.urandom(8).hex(), "session_cookie": os.urandom(8).hex()}
    expiry = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    response = client.put("/api/lab-credentials/neri-local/viewer", json={"values": new, "expires_at": expiry})

    assert response.status_code == 200
    from app.storage.credentials import decrypt_value

    stored = json.loads(decrypt_value(table.rows[0].value_encrypted))
    assert stored["values"] == new and stored["kind"] == "synthetic" and stored["expires_at"]
    assert all(value not in response.text for value in new.values())


def test_replace_refuses_temporary_missing_and_mixed_bodies(client, table):
    table.rows.append(row("neri-local", "temp", "temporary", {"password": "x"},
                          expires_at=datetime.now(UTC) + timedelta(days=1)))
    before = table.rows[0].value_encrypted

    assert client.put("/api/lab-credentials/neri-local/temp", json={"values": {"password": "n"}}).status_code == 400
    assert table.rows[0].value_encrypted == before
    assert client.put("/api/lab-credentials/neri-local/nobody", json={"values": {"password": "n"}}).status_code == 404
    mixed = client.put("/api/lab-credentials/neri-local/temp", json={"values": {"a": "b"}, "username": "u"})
    assert mixed.status_code == 400
    assert client.put("/api/lab-credentials/neri-local/temp", json={"username": "u"}).status_code == 400


def test_delete_removes_exactly_one_row_even_when_it_cannot_be_decoded(client, table):
    keep = row("neri-local", "viewer", "synthetic", {"password": "x"})
    junk = row("st-login-selftest", "default", "synthetic", {"password": "x"})
    junk.value_encrypted = b"garbage"
    table.rows += [keep, junk]

    response = client.delete("/api/lab-credentials/st-login-selftest/default")

    assert response.status_code == 204 and response.content == b""
    assert table.rows == [keep]
    assert table.locks == 1
    assert client.delete("/api/lab-credentials/st-login-selftest/default").status_code == 404


def test_delete_changes_nothing_for_duplicates_or_bad_references(client, table):
    table.rows += [row("neri-local", "viewer", "synthetic", {"password": "x"}) for _ in range(2)]

    assert client.delete("/api/lab-credentials/neri-local/viewer").status_code == 400
    assert len(table.rows) == 2
    assert client.delete("/api/lab-credentials/Bad_Target/viewer").status_code == 400
    table.db.delete.assert_not_awaited()


def _stored(table, index=0):
    from app.storage.credentials import decrypt_value

    return json.loads(decrypt_value(table.rows[index].value_encrypted))


def test_patch_changes_only_the_named_fields_and_keeps_the_kind(client, table):
    original = {**generated(), "login_url": "https://hackerone.com/login", "totp_secret": SECRET}
    table.rows.append(row("hackerone", "default", "account", original))
    password = os.urandom(12).hex()

    response = client.patch("/api/lab-credentials/hackerone/default", json={"set": {"password": password}})

    assert response.status_code == 200 and response.json() == {"reference": "secret://lab/hackerone/default"}
    stored = _stored(table)
    assert stored["kind"] == "account" and stored["expires_at"] is None
    assert stored["values"] == {**original, "password": password}
    assert password not in response.text and table.locks == 1


def test_patch_normalises_totp_and_login_url_and_can_remove_the_secret(client, table):
    table.rows.append(row("hackerone", "default", "account", {**generated(), "login_url": "https://a.example/"}))

    added = client.patch("/api/lab-credentials/hackerone/default", json={"set": {
        "totp_secret": f"otpauth://totp/x?secret={SECRET.lower()}", "login_url": "https://a.example/login",
    }})
    assert added.status_code == 200
    assert _stored(table)["values"]["totp_secret"] == SECRET
    assert _stored(table)["values"]["login_url"] == "https://a.example/login"

    for bad in ({"login_url": "http://example.com"}, {"totp_secret": f"otpauth://totp/x?secret={SECRET}&digits=8"}):
        assert client.patch("/api/lab-credentials/hackerone/default", json={"set": bad}).status_code == 400

    removed = client.patch("/api/lab-credentials/hackerone/default", json={"remove": ["totp_secret"]})
    assert removed.status_code == 200
    assert "totp_secret" not in _stored(table)["values"]


def test_patch_expiry_is_kept_unless_given_and_null_clears_it(client, table):
    future = datetime.now(UTC) + timedelta(days=3)
    table.rows.append(row("neri-local", "viewer", "synthetic", {"password": "x"}, expires_at=future))
    kept = _stored(table)["expires_at"]

    assert client.patch("/api/lab-credentials/neri-local/viewer", json={"set": {"password": "y"}}).status_code == 200
    assert _stored(table)["expires_at"] == kept

    later = (datetime.now(UTC) + timedelta(days=9)).replace(microsecond=0)
    assert client.patch("/api/lab-credentials/neri-local/viewer", json={"expires_at": later.isoformat()}).status_code == 200
    assert datetime.fromisoformat(_stored(table)["expires_at"]) == later

    assert client.patch("/api/lab-credentials/neri-local/viewer", json={"expires_at": None}).status_code == 200
    assert _stored(table)["expires_at"] is None
    assert _stored(table)["values"] == {"password": "y"}


def test_patch_refuses_unsafe_edits_without_changing_the_row(client, table):
    table.rows += [
        row("hackerone", "default", "account", {**generated(), "login_url": "https://hackerone.com/login"}),
        row("neri-local", "temp", "temporary", {"password": "x"}, expires_at=datetime.now(UTC) + timedelta(days=1)),
    ]
    before = [item.value_encrypted for item in table.rows]

    cases = [
        ("hackerone/default", {"remove": ["password"]}),
        ("hackerone/default", {"remove": ["nothing_here"]}),
        ("hackerone/default", {"set": {"password": "x"}, "remove": ["password"]}),
        ("hackerone/default", {"set": {"bad name": "x"}}),
        ("neri-local/temp", {"set": {"password": "y"}}),
    ]
    for path, body in cases:
        assert client.patch(f"/api/lab-credentials/{path}", json=body).status_code == 400, body
    assert client.patch("/api/lab-credentials/neri-local/nobody", json={"set": {"a": "b"}}).status_code == 404
    assert [item.value_encrypted for item in table.rows] == before


def test_changing_the_site_needs_the_password_again_but_the_same_origin_does_not(client, table):
    original = {**generated(), "login_url": "https://hackerone.com/users/sign_in"}
    table.rows.append(row("hackerone", "default", "account", original))
    before = table.rows[0].value_encrypted
    path = "/api/lab-credentials/hackerone/default"

    for other in ("https://evil.example/login", "https://hackerone.com.evil.example/login", "https://hackerone.com:8443/login"):
        response = client.patch(path, json={"set": {"login_url": other}})
        assert response.status_code == 400
        assert response.json()["message"] == "Changing the site needs the password again"
    assert table.rows[0].value_encrypted == before

    assert client.patch(path, json={"set": {"login_url": "https://hackerone.com:443/login"}}).status_code == 200
    assert _stored(table)["values"]["login_url"] == "https://hackerone.com:443/login"

    password = os.urandom(12).hex()
    moved = client.patch(path, json={"set": {"login_url": "https://example.org/login", "password": password}})
    assert moved.status_code == 200
    assert _stored(table)["values"]["password"] == password
    assert _stored(table)["values"]["login_url"] == "https://example.org/login"


def test_replacing_with_values_cannot_move_the_site_without_a_password(client, table):
    table.rows.append(row("hackerone", "default", "account", {**generated(), "login_url": "https://hackerone.com/login"}))
    before = table.rows[0].value_encrypted

    response = client.put("/api/lab-credentials/hackerone/default", json={"values": {
        "username": "u", "login_url": "https://evil.example/login",
    }})

    assert response.status_code == 400 and table.rows[0].value_encrypted == before
