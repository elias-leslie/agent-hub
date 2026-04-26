"""Tests for dedicated memory review agent orchestration."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.adapters.base import AuthenticationError
from app.services.memory.review_agent import (
    MemoryReviewDecision,
    _call_reviewer_agent,
    build_memory_review_prompt,
    parse_memory_review_content,
    run_memory_review_batch,
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
    )

    assert "codex_startup" in prompt
    assert "claude_session_start" in prompt
    assert "Use st search before repo spelunking." in prompt


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
