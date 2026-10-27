"""A chat session reuses its first canonical delivery so provider caches keep hitting."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest

from app.services.canonical_context_adapters import progressive_context_from_delivery
from app.services.memory import context_freeze
from app.services.memory.context_injector_ops import (
    _build_delivery,
    inject_memory_block,
)
from app.services.memory.service import MemoryScope
from app.services.runtime_context import (
    CanonicalContextBlock,
    CanonicalContextDeliveryResponse,
    CanonicalContextMetadata,
    CanonicalContextProvenance,
    CanonicalPolicyCompleteness,
)


class FakeRedis:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int | None] = {}

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, ex=None):
        self.data[key] = value
        self.ttls[key] = ex


def _block(order: int, kind: str, source_id: str, text: str) -> CanonicalContextBlock:
    return CanonicalContextBlock(
        order=order,
        block_id=f"memory:{source_id}",
        kind=kind,
        authority="advisory_reference" if kind in {"reference", "capability"} else "operator_guardrail",
        required=kind == "guardrail",
        title=text[:20],
        content=text,
        estimated_tokens=5,
        provenance=CanonicalContextProvenance(
            source_type="memory",
            source_id=source_id,
            source_revision="sha256:x",
            origin="auto",
            scope="global",
        ),
    )


def _delivery(query: str, reference_id: str, status: str = "ok") -> CanonicalContextDeliveryResponse:
    blocks = [
        _block(0, "guardrail", "g1", "Guardrail text"),
        _block(1, "reference", reference_id, f"Reference for {query}"),
        _block(2, "capability", "idx1", "Indexed on demand"),
    ]
    return CanonicalContextDeliveryResponse(
        delivery_id=f"d-{query}",
        artifact_id=f"a-{query}",
        generated_at=datetime.now(UTC),
        status=status,
        payload_hash="h",
        metadata=CanonicalContextMetadata(
            consumer_surface="agent_runtime", consumer_profile="agent_runtime", query=query, query_hash="q"
        ),
        blocks=blocks,
        rendered="\n".join(block.content for block in blocks),
        estimated_tokens=15,
        required_policy=CanonicalPolicyCompleteness(state="complete"),
    )


@pytest.fixture
def harness():
    fake = FakeRedis()
    built: list[str] = []
    workflows: list[str] = []

    async def fake_build(_db, request):
        built.append(request.query)
        return _delivery(request.query, f"ref-{request.query}")

    with (
        patch.object(context_freeze, "_redis", return_value=fake),
        patch("app.services.runtime_context.build_canonical_context_delivery", fake_build),
        patch("app.services.memory.context_injector_ops.get_memory_settings", AsyncMock(
            return_value=type("S", (), {
                "continuity_enabled": True, "continuity_max_sessions": 3,
                "continuity_cross_project": False, "continuity_live_sessions": False,
            })()
        )),
        patch("app.services.context_governance.session_workflows", AsyncMock(side_effect=lambda *_: list(workflows))),
    ):
        yield fake, built, workflows


async def _deliver(query: str, *, session_id: str | None = "sess-1", phase: str | None = None):
    delivery, _variant = await _build_delivery(
        db=object(), messages=[{"role": "user", "content": query}], scope=MemoryScope.GLOBAL,
        scope_id=None, query=query, variant=None, session_id=session_id, external_id=None,
        project_id="agent-hub", task_type=None, phase=phase, include_continuity=True,
        memory_config=None, current_branch=None, consumer_surface="agent_runtime",
        consumer_profile="agent_runtime", consumer_agent_slug="coder", consumer_tags=None,
        include_prompts=True, include_memories=True,
    )
    return delivery


@pytest.mark.asyncio
async def test_later_turns_reuse_first_delivery_byte_for_byte(harness):
    fake, built, _ = harness
    first = await _deliver("first question")
    second = await _deliver("totally different topic")
    third = await _deliver("and another one")
    assert built == ["first question"]
    assert second.rendered == third.rendered == first.rendered
    system = [
        inject_memory_block([{"role": "user", "content": q}], d.rendered)[0]["content"]
        for q, d in (("a", first), ("b", second), ("c", third))
    ]
    assert system[0] == system[1] == system[2]
    assert list(fake.ttls.values()) == [3600]


@pytest.mark.asyncio
async def test_reused_delivery_keeps_selected_and_indexed_references_separate(harness):
    first = await _deliver("first question")
    reused = await _deliver("second question")
    assert reused.delivery_id == first.delivery_id
    live = progressive_context_from_delivery(first)
    frozen = progressive_context_from_delivery(reused)
    assert frozen.get_loaded_uuids() == live.get_loaded_uuids()
    assert frozen.get_reference_uuids() == ["ref-first question"]
    assert frozen.get_reference_index_uuids() == ["idx1"]
    assert [b.block_id for b in reused.blocks] == [b.block_id for b in first.blocks]


@pytest.mark.asyncio
async def test_selection_inputs_other_than_the_query_rebuild(harness):
    _, built, workflows = harness
    await _deliver("q1")
    await _deliver("q2", phase="review")
    assert built == ["q1", "q2"]
    workflows.append("workflow-a")
    await _deliver("q3")
    assert built == ["q1", "q2", "q3"]
    await _deliver("q4")
    assert built == ["q1", "q2", "q3"]


@pytest.mark.asyncio
async def test_other_sessions_and_ephemeral_calls_never_share(harness):
    fake, built, _ = harness
    await _deliver("q1", session_id="sess-1")
    await _deliver("q2", session_id="sess-2")
    await _deliver("q3", session_id="ephemeral:abc")
    await _deliver("q4", session_id="ephemeral:abc")
    await _deliver("q5", session_id=None)
    assert built == ["q1", "q2", "q3", "q4", "q5"]
    assert len(fake.data) == 2


@pytest.mark.asyncio
async def test_redis_failure_falls_back_to_live_delivery(harness):
    _, built, _ = harness

    class Broken:
        async def get(self, _key):
            raise ConnectionError("down")

        async def set(self, *_a, **_k):
            raise ConnectionError("down")

    with patch.object(context_freeze, "_redis", return_value=Broken()):
        await _deliver("q1")
        await _deliver("q2")
    assert built == ["q1", "q2"]


@pytest.mark.asyncio
async def test_failed_deliveries_are_not_frozen(harness):
    fake, _, _ = harness
    await context_freeze.store_frozen_delivery("k", _delivery("q", "r", status="failed"))
    assert fake.data == {}


@pytest.mark.asyncio
async def test_ttl_zero_disables_reuse(harness):
    _, built, _ = harness
    with patch.object(context_freeze.settings, "agent_hub_context_freeze_ttl_seconds", 0):
        await _deliver("q1")
        await _deliver("q2")
    assert built == ["q1", "q2"]
