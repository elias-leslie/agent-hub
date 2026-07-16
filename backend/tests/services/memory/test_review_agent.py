"""Tests for dedicated memory review agent orchestration."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.llm_errors import AuthenticationError
from app.services.memory.review_agent import (
    MemoryReviewDecision,
    _apply_decision,
    _call_reviewer_agent,
    _normalize_compact_content,
    build_memory_review_prompt,
    parse_memory_review_content,
    repair_memory_review_content,
    run_memory_review_batch,
    select_memories_due_for_review,
)


def _memory(**overrides):
    defaults = {
        "id": "11111111-1111-1111-1111-111111111111",
        "uuid_short": "11111111",
        "name": "Use st",
        "summary": "use st",
        "content": "Use st search before repo spelunking.",
        "memory_type": "mandate",
        "tier": 1,
        "context_kind": "policy",
        "scope": "global",
        "scope_id": None,
        "group_id": None,
        "tags": ["tooling"],
        "applicability": {},
        "trigger_task_types": [],
        "trigger_phases": [],
        "loaded_count": 1,
        "referenced_count": 1,
        "helpful_count": 1,
        "harmful_count": 0,
        "token_count": 10,
        "review_status": "pending",
        "last_reviewed_at": None,
        "metadata_": {},
        "sensitivity_tier": "normal",
        "status": "active",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC),
        "updated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_parse_memory_review_content_accepts_valid_response() -> None:
    parsed = parse_memory_review_content(
        """
        {"reviews": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "keep",
          "review_status": "clean",
          "confidence": 0.92,
          "reason": "Still compact and correctly scoped.",
          "suggested_summary": "use st search",
          "suggested_tags": ["tooling"],
          "suggested_applicability": {},
          "sensitivity_tier": "normal"
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="keep",
            review_status="clean",
            confidence=0.92,
            reason="Still compact and correctly scoped.",
            suggested_summary="use st search",
            suggested_tags=["tooling"],
            suggested_applicability={},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_accepts_null_suggested_tags() -> None:
    parsed = parse_memory_review_content(
        """
        {"reviews": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "keep",
          "review_status": "clean",
          "reason": "Current.",
          "suggested_tags": null
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed is not None
    assert parsed[0].suggested_tags == []


def test_parse_memory_review_content_rejects_unknown_uuid() -> None:
    parsed = parse_memory_review_content(
        """
        {"reviews": [{
          "uuid": "22222222-2222-2222-2222-222222222222",
          "decision": "keep",
          "review_status": "clean",
          "confidence": 1,
          "reason": "ok",
          "suggested_summary": null,
          "suggested_tags": [],
          "suggested_applicability": {},
          "sensitivity_tier": "normal"
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed is None


def test_parse_memory_review_content_rejects_incomplete_or_duplicate_batch() -> None:
    expected = {
        "11111111-1111-1111-1111-111111111111",
        "22222222-2222-2222-2222-222222222222",
    }
    item = {
        "uuid": "11111111-1111-1111-1111-111111111111",
        "decision": "keep",
        "review_status": "clean",
        "reason": "Current and appropriate.",
    }

    assert parse_memory_review_content('{"reviews": [' + json.dumps(item) + "]}", expected) is None
    assert (
        parse_memory_review_content(
            '{"reviews": ['
            + json.dumps(item)
            + ","
            + json.dumps(item)
            + "]}",
            expected,
        )
        is None
    )


def test_parse_memory_review_content_accepts_json_fence() -> None:
    parsed = parse_memory_review_content(
        """```json
        {"reviews": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "keep",
          "review_status": "clean",
          "reason": "Current and appropriate."
        }]}
        ```""",
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed is not None
    assert parsed[0].uuid == "11111111-1111-1111-1111-111111111111"


def test_repair_memory_review_content_quarantines_missing_checks() -> None:
    repaired = repair_memory_review_content(
        """
        {"reviews": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "keep",
          "review_status": "clean",
          "reason": "Reviewer omitted most checks.",
          "checks": {"currency": "pass"}
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert repaired is not None
    parsed = parse_memory_review_content(
        repaired,
        {"11111111-1111-1111-1111-111111111111"},
    )
    assert parsed is not None
    assert parsed[0].review_status == "needs_action"
    assert parsed[0].checks["currency"] == "pass"
    assert parsed[0].checks["correctness"] == "unknown"


def test_parse_memory_review_content_accepts_codex_compact_shape() -> None:
    parsed = parse_memory_review_content(
        """
        {"decisions": [{
          "uuid8": "11111111",
          "decision": "needs_action",
          "evidence": "Too broad for startup context."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="Too broad for startup context.",
            suggested_summary=None,
            suggested_tags=[],
            suggested_applicability={},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_uses_uuid8_when_full_uuid_wrong() -> None:
    parsed = parse_memory_review_content(
        """
        {"reviews": [{
          "uuid": "11111111-2222-2222-2222-222222222222",
          "uuid8": "11111111",
          "decision": "keep",
          "evidence": "Correct uuid8, wrong generated suffix."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="keep",
            review_status="clean",
            confidence=0.75,
            reason="Correct uuid8, wrong generated suffix.",
            suggested_summary=None,
            suggested_tags=[],
            suggested_applicability={},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_accepts_top_level_array_shape() -> None:
    parsed = parse_memory_review_content(
        """
        [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "keep",
          "needs_action": false,
          "evidence": "Compact and correctly routed."
        }]
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="keep",
            review_status="clean",
            confidence=0.75,
            reason="Compact and correctly routed.",
            suggested_summary=None,
            suggested_tags=[],
            suggested_applicability={},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_accepts_ok_alias() -> None:
    parsed = parse_memory_review_content(
        """
        {"reviews": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "ok",
          "evidence": "Still compact."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="keep",
            review_status="clean",
            confidence=0.75,
            reason="Still compact.",
            suggested_summary=None,
            suggested_tags=[],
            suggested_applicability={},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_accepts_curator_target_compact_alias() -> None:
    parsed = parse_memory_review_content(
        """
        {"decisions": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "uuid8": "11111111",
          "review_status": "needs_action",
          "decision": "keep_compact_target",
          "evidence": "Broad reference should be targeted and compacted.",
          "target_consumers": ["agent_coding"],
          "compact_content": "**Search**: Use st search before repo spelunking."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="Broad reference should be targeted and compacted.",
            suggested_summary=None,
            compact_content="**Search**: Use st search before repo spelunking.",
            suggested_tags=[],
            suggested_applicability={"consumer_profiles": ["agent_coding"]},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_uses_issues_and_applicability() -> None:
    parsed = parse_memory_review_content(
        """
        {"decisions": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "review_status": "needs_action",
          "issues": ["too broad", "needs target"],
          "decision": "keep_compact_retarget",
          "applicability": {"consumer_profiles": ["agent_runtime"]},
          "compact_content": "**Ports**: Use project index for current service ports."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="too broad; needs target",
            suggested_summary=None,
            compact_content="**Ports**: Use project index for current service ports.",
            suggested_tags=[],
            suggested_applicability={"consumer_profiles": ["agent_runtime"]},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_uses_reasons_and_assignment() -> None:
    parsed = parse_memory_review_content(
        """
        [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "needs_action",
          "reasons": ["useful", "global reference too broad"],
          "assignment": {"consumer_profiles": ["agent_operator"]},
          "compact_content": "**Ports**: Use project index for service ports."
        }]
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="useful; global reference too broad",
            suggested_summary=None,
            compact_content="**Ports**: Use project index for service ports.",
            suggested_tags=[],
            suggested_applicability={"consumer_profiles": ["agent_operator"]},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_infers_decision_from_status_and_routing() -> None:
    parsed = parse_memory_review_content(
        """
        {"decisions": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "review_status": "needs_action",
          "issues": ["untargeted_reference"],
          "routing": ["agent_operator"],
          "compact_content": "**Proxy**: Check Caddy and cloudflared configs for external routing."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="untargeted_reference",
            suggested_summary=None,
            compact_content="**Proxy**: Check Caddy and cloudflared configs for external routing.",
            suggested_tags=[],
            suggested_applicability={"consumer_profiles": ["agent_operator"]},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_normalizes_targeting_status() -> None:
    parsed = parse_memory_review_content(
        """
        [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "needs_action",
          "review_status": "keep_compact_and_target",
          "evidence": "Useful but untargeted.",
          "targeting": {"consumer_profiles": ["agent_coding"], "scope": "project"},
          "compact_content": "**Logs**: Use journald for service logs."
        }]
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="Useful but untargeted.",
            suggested_summary=None,
            compact_content="**Logs**: Use journald for service logs.",
            suggested_tags=[],
            suggested_applicability={"consumer_profiles": ["agent_coding"], "scope": "project"},
            sensitivity_tier="normal",
        )
    ]


def test_parse_memory_review_content_accepts_rationale_and_recommended_fields() -> None:
    parsed = parse_memory_review_content(
        """
        {"decisions": [{
          "uuid": "11111111-1111-1111-1111-111111111111",
          "decision": "needs_action",
          "rationale": "Useful but project-specific and untargeted.",
          "recommended_context_kind": "reference",
          "recommended_tier": "reference",
          "recommended_scope": "project",
          "recommended_scope_id": "summitflow",
          "recommended_consumer_profiles": ["agent_operator"],
          "compact_content": "**Hermes**: Use journald for gateway logs."
        }]}
        """,
        {"11111111-1111-1111-1111-111111111111"},
    )

    assert parsed == [
        MemoryReviewDecision(
            uuid="11111111-1111-1111-1111-111111111111",
            decision="retarget",
            review_status="needs_action",
            confidence=0.75,
            reason="Useful but project-specific and untargeted.",
            suggested_summary=None,
            compact_content="**Hermes**: Use journald for gateway logs.",
            suggested_tags=[],
            suggested_applicability={
                "scope": "project",
                "scope_id": "summitflow",
                "context_kind": "reference",
                "tier": "reference",
                "consumer_profiles": ["agent_operator"],
            },
            sensitivity_tier="normal",
        )
    ]


def test_build_memory_review_prompt_includes_assignment_context() -> None:
    prompt = build_memory_review_prompt(
        [_memory()],
        governance_snapshot={"health_status": "healthy"},
        authority_prompts=[
            SimpleNamespace(
                slug="project-policy",
                prompt_type="standard",
                is_global=False,
                content="Project prompt owns reusable workflow.",
            )
        ],
        authority_prompt_assignments=[
            {
                "prompt_slug": "project-policy",
                "consumer_profile": "agent_coding",
                "project_id": "agent-hub",
                "mode": "include",
                "enabled": True,
            }
        ],
        computed_tool_capabilities="<tool-usage>st search owns code lookup</tool-usage>",
    )

    assert prompt.startswith("Governance snapshot JSON:")
    assert "Use st search before repo spelunking." in prompt
    assert '"token_efficiency"' in prompt
    assert '"consumer_surfaces"' in prompt
    assert '"exclude_consumer_surfaces"' in prompt
    assert '"is_global":false' in prompt
    assert '"project_id":"agent-hub"' in prompt
    assert "<tool-usage>st search owns code lookup</tool-usage>" in prompt


def test_compact_content_is_never_hard_cropped() -> None:
    candidate = "Must preserve every required clause. " + "concise evidence " * 35
    original = candidate + ("additional non-normative background " * 20)

    compact = _normalize_compact_content(original=original, candidate=candidate)

    assert compact == " ".join(candidate.split())
    assert len(compact) > 420


def test_compact_content_rejects_lost_normative_force() -> None:
    original = "Must use canonical data. Never add duplicate downloads. Background details follow."
    candidate = "Use canonical data and avoid duplicate downloads."

    assert _normalize_compact_content(original=original, candidate=candidate) is None


def test_apply_decision_archives_high_confidence_stale_memory() -> None:
    memory = _memory(
        version=3,
        pinned=True,
        auto_inject=True,
        retired_at=None,
        superseded_by=None,
    )
    decision = MemoryReviewDecision(
        uuid=str(memory.id),
        decision="archive",
        review_status="needs_action",
        confidence=0.96,
        reason="Superseded project-state fact.",
        checks={"currency": "concern", "correctness": "pass"},
    )

    _apply_decision(
        memory,
        decision,
        datetime.now(UTC),
        active_memory_ids={str(memory.id)},
    )

    assert memory.status == "archived"
    assert memory.tier == 4
    assert memory.pinned is False
    assert memory.auto_inject is False
    assert memory.metadata_["last_review"]["applied_remediations"] == ["archived"]


def test_apply_decision_does_not_archive_unknown_or_low_confidence_memory() -> None:
    for confidence, checks in (
        (0.7, {"currency": "concern"}),
        (0.99, {"currency": "unknown"}),
    ):
        memory = _memory(version=1, retired_at=None, superseded_by=None)
        decision = MemoryReviewDecision(
            uuid=str(memory.id),
            decision="archive",
            review_status="needs_action",
            confidence=confidence,
            reason="Insufficient evidence.",
            checks=checks,
        )

        _apply_decision(
            memory,
            decision,
            datetime.now(UTC),
            active_memory_ids={str(memory.id)},
        )

        assert memory.status == "active"
        assert memory.metadata_["last_review"]["applied_remediations"] == []


def test_apply_decision_keeps_valid_policy_until_prompt_migration() -> None:
    memory = _memory(
        version=1,
        context_kind="policy",
        tier=1,
        retired_at=None,
        superseded_by=None,
    )
    decision = MemoryReviewDecision(
        uuid=str(memory.id),
        decision="archive",
        review_status="needs_action",
        confidence=0.99,
        reason="Valid rule belongs in a delivered DB prompt, but no replacement exists yet.",
        checks={
            "currency": "pass",
            "correctness": "pass",
            "appropriateness": "concern",
            "scope_applicability": "pass",
            "conflict": "pass",
            "redundancy": "pass",
            "lifecycle": "pass",
            "authority": "pass",
            "token_efficiency": "pass",
        },
    )

    _apply_decision(
        memory,
        decision,
        datetime.now(UTC),
        active_memory_ids={str(memory.id)},
    )

    assert memory.status == "active"
    assert memory.metadata_["last_review"]["prompt_migration_required"] is True
    assert memory.metadata_["last_review"]["applied_remediations"] == []


def test_apply_decision_retargets_high_confidence_reference() -> None:
    memory = _memory(
        version=1,
        scope="global",
        scope_id=None,
        tier=1,
        memory_type="mandate",
        context_kind="policy",
        applicability={},
    )
    decision = MemoryReviewDecision(
        uuid=str(memory.id),
        decision="retarget",
        review_status="needs_action",
        confidence=0.97,
        reason="Project-specific reference was globally authoritative.",
        checks={"scope_applicability": "concern", "authority": "concern"},
        suggested_applicability={
            "scope": "project",
            "scope_id": "agent-hub",
            "context_kind": "reference",
            "tier": "reference",
            "consumer_profiles": ["agent_runtime"],
            "consumer_surfaces": ["codex", "claude", "pi"],
            "exclude_consumer_surfaces": ["gemini"],
            "trigger_task_types": ["browser", "frontend"],
            "trigger_phases": ["verify", "qa"],
        },
    )

    _apply_decision(
        memory,
        decision,
        datetime.now(UTC),
        active_memory_ids={str(memory.id)},
    )

    assert memory.scope == "project"
    assert memory.scope_id == "agent-hub"
    assert memory.context_kind == "reference"
    assert memory.tier == 3
    assert memory.memory_type == "reference"
    assert memory.applicability == {
        "consumer_profiles": ["agent_runtime"],
        "consumer_surfaces": ["codex", "claude", "pi"],
        "exclude_consumer_surfaces": ["gemini"],
    }
    assert memory.trigger_task_types == ["browser", "frontend"]
    assert memory.trigger_phases == ["verify", "qa"]


def test_apply_decision_applies_high_confidence_summary_and_tags() -> None:
    memory = _memory(version=1, summary="Old summary", tags=["existing"])
    decision = MemoryReviewDecision(
        uuid=str(memory.id),
        decision="compress",
        review_status="needs_action",
        confidence=0.97,
        reason="Summary and classification are stale; full content remains canonical.",
        checks={"token_efficiency": "concern"},
        suggested_summary="Current concise summary",
        suggested_tags=["existing", "memory-review"],
    )

    _apply_decision(
        memory,
        decision,
        datetime.now(UTC),
        active_memory_ids={str(memory.id)},
    )

    assert memory.summary == "Current concise summary"
    assert memory.tags == ["existing", "memory-review"]
    assert memory.metadata_["last_review"]["applied_remediations"] == ["summary", "tags"]


@pytest.mark.asyncio
async def test_run_memory_review_batch_marks_last_reviewed() -> None:
    memory = _memory(
        content=(
            "Use st search before repo spelunking so agents start from canonical "
            "repo evidence instead of broad manual file browsing."
        )
    )
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = [memory]
    mock_db = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.execute.return_value = execute_result

    with (
        patch(
            "app.services.memory.review_agent.collect_memory_governance_snapshot",
            new_callable=AsyncMock,
            return_value={"health_status": "healthy"},
        ),
        patch(
            "app.services.memory.review_agent._call_reviewer_agent",
            new_callable=AsyncMock,
            return_value=(
                """
                {"reviews": [{
                  "uuid": "11111111-1111-1111-1111-111111111111",
                  "decision": "keep",
                  "review_status": "clean",
                  "confidence": 0.9,
                  "reason": "Still useful.",
                  "checks": {
                    "currency": "pass",
                    "correctness": "pass",
                    "appropriateness": "pass",
                    "scope_applicability": "pass",
                    "conflict": "pass",
                    "redundancy": "pass",
                    "lifecycle": "pass",
                    "authority": "pass",
                    "token_efficiency": "pass"
                  },
                  "suggested_summary": "use st search",
                  "compact_content": "Use st search before repo spelunking.",
                  "suggested_tags": ["tooling"],
                  "suggested_applicability": {},
                  "sensitivity_tier": "normal"
                }]}
                """,
                "codex/gpt-5.5",
                "session-1",
            ),
        ),
    ):
        result = await run_memory_review_batch(db=mock_db, batch_limit=1)

    assert result.status == "completed"
    assert result.reviewed_count == 1
    assert memory.review_status == "clean"
    assert memory.last_reviewed_at is not None
    assert memory.metadata_["last_review"]["decision"] == "keep"
    assert memory.metadata_["compact_content"] == "Use st search before repo spelunking."


@pytest.mark.asyncio
async def test_select_memories_due_for_review_respects_source_compact_validation() -> None:
    execute_result = MagicMock()
    execute_result.scalars.return_value.all.return_value = []
    mock_db = AsyncMock()
    mock_db.execute.return_value = execute_result

    await select_memories_due_for_review(mock_db, limit=1)

    stmt = mock_db.execute.await_args.args[0]
    compiled = str(stmt)
    params = list(stmt.compile().params.values())
    assert "source_compact_validated_at" in params
    assert "coalesce" in compiled.lower()


@pytest.mark.asyncio
async def test_call_reviewer_agent_does_not_fallback_on_auth_failure() -> None:
    mock_db = AsyncMock()
    resolved_agent = SimpleNamespace(
        temperature=0.2,
        fallback_models=["claude-sonnet-4-6"],
        thinking_level="medium",
    )
    resolved = SimpleNamespace(
        agent=resolved_agent,
        model="codex/gpt-5.5",
        provider="codex",
    )
    mandate = SimpleNamespace(system_content="system")

    with (
        patch(
            "app.services.agent_routing_utils.resolve_agent",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch(
            "app.services.agent_routing_utils.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=mandate,
        ),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            side_effect=AuthenticationError("codex"),
        ) as complete_internal,pytest.raises(AuthenticationError)
    ):
        await _call_reviewer_agent(
            mock_db,
            reviewer_agent_slug="memory-curator",
            prompt="review",
        )

    assert complete_internal.await_count == 1


@pytest.mark.asyncio
async def test_call_reviewer_agent_falls_back_on_empty_content() -> None:
    mock_db = AsyncMock()
    resolved_agent = SimpleNamespace(
        temperature=0.2,
        fallback_models=["codex/gpt-5.4-mini"],
        thinking_level="medium",
    )
    resolved = SimpleNamespace(
        agent=resolved_agent,
        model="kimi-code/kimi-for-coding",
        provider="kimi-code",
    )
    mandate = SimpleNamespace(system_content="system")
    valid = (
        '{"reviews":[{"uuid":"11111111-1111-1111-1111-111111111111",'
        '"decision":"keep","review_status":"clean","reason":"Current.",'
        '"checks":{"currency":"pass","correctness":"pass",'
        '"appropriateness":"pass","scope_applicability":"pass",'
        '"conflict":"pass","redundancy":"pass","lifecycle":"pass",'
        '"authority":"pass","token_efficiency":"pass"}}]}'
    )

    with (
        patch(
            "app.services.agent_routing_utils.resolve_agent",
            new_callable=AsyncMock,
            return_value=resolved,
        ),
        patch(
            "app.services.agent_routing_utils.inject_agent_mandates",
            new_callable=AsyncMock,
            return_value=mandate,
        ),
        patch(
            "app.services.agent_routing.get_provider_for_model",
            return_value="codex",
        ),
        patch(
            "app.api.complete.core.complete_internal",
            new_callable=AsyncMock,
            side_effect=[
                SimpleNamespace(content="", session_id="empty-session"),
                SimpleNamespace(content=valid, session_id="valid-session"),
            ],
        ) as complete_internal,
    ):
        content, model, session_id = await _call_reviewer_agent(
            mock_db,
            reviewer_agent_slug="memory-curator",
            prompt="review",
            expected_uuids={"11111111-1111-1111-1111-111111111111"},
        )

    assert content == valid
    assert model == "codex/gpt-5.4-mini"
    assert session_id == "valid-session"
    assert complete_internal.await_count == 2
