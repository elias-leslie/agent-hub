"""Exercise the public packaged contract without network calls or real secrets."""

import importlib
from pathlib import Path

import httpx
import pytest

from app.services.session_ingestion.app_server_observations import protocol_contract


@pytest.mark.asyncio
async def test_async_native_delivery_sends_internal_authority_and_preserves_v1(monkeypatch):
    package = Path(__file__).resolve().parents[4] / "packages/agent-hub-client"
    monkeypatch.syspath_prepend(str(package))
    sdk = importlib.import_module("agent_hub")
    models = importlib.import_module("agent_hub.models.native_observation")
    protocol = importlib.import_module("agent_hub.codex_protocol")
    assert protocol.fingerprint() == protocol_contract()[0]
    requests = []

    def transport(request):
        requests.append(request)
        result = {"schema_version": "native-observation.v1", "source_id": "fixture", "authenticity": "collector_attested", "committed_position": 0}
        if request.url.path.endswith("/observations"):
            result["dispositions"] = []
        return httpx.Response(200, json=result)

    async with sdk.AsyncAgentHubClient(base_url="http://fixture.invalid", client_id="summitflow-fixture", request_source="codex-managed-capture") as client:
        client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(transport), headers=client._build_base_headers())
        registration = models.NativeSourceRegistration(namespace="fixture", source_kind="app_server", producer_id="owner", epoch="epoch", collector_id="summitflow/codex-managed", provider_version=protocol.SUPPORTED_VERSION, schema_fingerprint=protocol.fingerprint(), thread_id="thread")
        await client.register_native_source("thread", registration, execution_owner_secret="owner-fixture")
        await client.ingest_native_observations("thread", "fixture", models.NativeObservationBatch(), execution_owner_secret="owner-fixture")
    assert [str(r.url) for r in requests] == ["http://fixture.invalid/api/session-ingestion/sessions/thread/native-sources", "http://fixture.invalid/api/session-ingestion/sessions/thread/native-sources/fixture/observations"]
    assert all(r.headers["X-Agent-Hub-Internal"] == "owner-fixture" for r in requests)
    assert all(r.headers["X-Client-Id"] == "summitflow-fixture" and r.headers["X-Request-Source"] == "codex-managed-capture" for r in requests)


@pytest.mark.asyncio
async def test_quarantine_sdk_preserves_absent_subject_and_version_profiles(monkeypatch):
    package = Path(__file__).resolve().parents[4] / "packages/agent-hub-client"
    monkeypatch.syspath_prepend(str(package))
    sdk = importlib.import_module("agent_hub")
    models = importlib.import_module("agent_hub.models.native_observation")
    protocol = importlib.import_module("agent_hub.codex_protocol")
    for version in protocol.SUPPORTED_VERSIONS:
        assert protocol.fingerprint(version) == protocol_contract(version)[0]
    with pytest.raises(ValueError, match="Unsupported"):
        protocol.schemas("codex-cli unknown")
    requests = []

    def transport(request):
        import json
        requests.append(request)
        if request.url.path.endswith("/observations"):
            body = json.loads(request.content)
            assert body["observations"][0]["thread_id"] is None
            return httpx.Response(200, json={"source_id": "quarantine", "authenticity": "collector_attested", "committed_position": 1, "dispositions": [{"position": 1, "disposition": "quarantined", "issue_code": "unbound_native_subject"}]})
        return httpx.Response(200, json={"source_id": "quarantine", "authenticity": "collector_attested", "committed_position": 0})

    registration = models.NativeQuarantineRegistration(project_id="agent-hub", namespace="fixture", producer_id="owner", epoch="epoch", collector_id="collector", provider_version=protocol.SUPPORTED_VERSION, schema_fingerprint=protocol.fingerprint())
    batch = models.NativeQuarantineBatch(observations=[models.NativeQuarantineObservation(position=1, payload={"method": "unbound"}, source_reference={"connection_id": "connection"})])
    async with sdk.AsyncAgentHubClient(base_url="http://fixture.invalid") as client:
        client._client = httpx.AsyncClient(base_url=client.base_url, transport=httpx.MockTransport(transport), headers=client._build_base_headers())
        receipt = await client.register_native_quarantine(registration, execution_owner_secret="owner-fixture")
        result = await client.ingest_native_quarantine(receipt.source_id, batch, execution_owner_secret="owner-fixture")
        assert result.committed_position == 1 and result.dispositions[0].disposition == "quarantined"
    with sdk.AgentHubClient(base_url="http://fixture.invalid") as client:
        client._client = httpx.Client(base_url=client.base_url, transport=httpx.MockTransport(transport), headers=client._build_base_headers())
        receipt = client.register_native_quarantine(registration, execution_owner_secret="owner-fixture")
        result = client.ingest_native_quarantine(receipt.source_id, batch, execution_owner_secret="owner-fixture")
        assert result.dispositions[0].position == 1
    assert len(requests) == 4
    assert all(request.headers["X-Agent-Hub-Internal"] == "owner-fixture" for request in requests)
