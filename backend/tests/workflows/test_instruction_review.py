"""Tests for supervisor instruction review gate."""

from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import AsyncMock, patch

import pytest

from app.workflows._instruction_review import (
    InstructionReviewOutcome,
    _build_review_prompt,
    _parse_review_content,
    review_instruction_edit,
)

# ── prompt builder ──


class TestBuildReviewPrompt:
    def test_includes_old_and_new(self):
        result = _build_review_prompt(
            old_instructions="Wait before acting.",
            new_instructions="Act immediately.",
            change_reason="Speed things up.",
        )
        assert "Wait before acting." in result
        assert "Act immediately." in result
        assert "Speed things up." in result

    def test_empty_old_shows_placeholder(self):
        result = _build_review_prompt(
            old_instructions="",
            new_instructions="New instructions here.",
            change_reason="Initial setup.",
        )
        assert "(empty)" in result
        assert "New instructions here." in result


# ── response parser ──


class TestParseReviewContent:
    def test_valid_approve(self):
        content = '{"decision": "approve", "reason": "Looks good"}'
        parsed = _parse_review_content(content)
        assert parsed == {"decision": "approve", "reason": "Looks good"}

    def test_valid_revise(self):
        content = '{"decision": "revise", "reason": "Weakens monitoring"}'
        parsed = _parse_review_content(content)
        assert parsed == {"decision": "revise", "reason": "Weakens monitoring"}

    def test_valid_reject(self):
        content = '{"decision": "reject", "reason": "Removes safety constraint"}'
        parsed = _parse_review_content(content)
        assert parsed == {"decision": "reject", "reason": "Removes safety constraint"}

    def test_invalid_decision(self):
        content = '{"decision": "maybe", "reason": "Uncertain"}'
        assert _parse_review_content(content) is None

    def test_missing_reason(self):
        content = '{"decision": "approve"}'
        assert _parse_review_content(content) is None

    def test_empty_reason(self):
        content = '{"decision": "approve", "reason": ""}'
        assert _parse_review_content(content) is None

    def test_malformed_json(self):
        assert _parse_review_content("not json") is None

    def test_none_content(self):
        assert _parse_review_content(None) is None


# ── integration: review_instruction_edit ──


@dataclass
class _FakeCompletionResult:
    content: str
    session_id: str = "test-session-123"
    model: str = "test-model"


@dataclass
class _FakeAgent:
    slug: str = "supervisor"
    temperature: float = 0.0
    thinking_level: str | None = None


@dataclass
class _FakeResolved:
    agent: _FakeAgent
    model: str = "claude-sonnet-4-6"
    provider: str = "claude"


@dataclass
class _FakeMandate:
    system_content: str = "You are the supervisor."
    injected_uuids: list[str] | None = None


def _make_async_session_ctx(mock_db=None):
    """Create a mock async context manager for async_session()."""
    db = mock_db or AsyncMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=db)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


class TestReviewInstructionEdit:
    @pytest.mark.asyncio
    async def test_approve_returns_used_outcome(self):
        mock_session = _make_async_session_ctx()
        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.workflows._instruction_review.resolve_agent",
                new_callable=AsyncMock,
                return_value=_FakeResolved(agent=_FakeAgent()),
            ),
            patch(
                "app.workflows._instruction_review.inject_agent_mandates",
                new_callable=AsyncMock,
                return_value=_FakeMandate(),
            ),
            patch(
                "app.workflows._instruction_review.complete_internal",
                new_callable=AsyncMock,
                return_value=_FakeCompletionResult(
                    content='{"decision": "approve", "reason": "Safe edit"}'
                ),
            ),
        ):
            outcome = await review_instruction_edit(
                old_instructions="Monitor before acting.",
                new_instructions="Monitor before acting. Also log observations.",
                change_reason="Better observability.",
            )

            assert outcome.used is True
            assert outcome.decision == "approve"
            assert outcome.reason == "Safe edit"

    @pytest.mark.asyncio
    async def test_reject_returns_used_outcome(self):
        mock_session = _make_async_session_ctx()
        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.workflows._instruction_review.resolve_agent",
                new_callable=AsyncMock,
                return_value=_FakeResolved(agent=_FakeAgent()),
            ),
            patch(
                "app.workflows._instruction_review.inject_agent_mandates",
                new_callable=AsyncMock,
                return_value=_FakeMandate(),
            ),
            patch(
                "app.workflows._instruction_review.complete_internal",
                new_callable=AsyncMock,
                return_value=_FakeCompletionResult(
                    content='{"decision": "reject", "reason": "Removes wait constraint"}'
                ),
            ),
        ):
            outcome = await review_instruction_edit(
                old_instructions="Always wait and verify.",
                new_instructions="Act immediately without delay.",
                change_reason="Be faster.",
            )

            assert outcome.used is True
            assert outcome.decision == "reject"
            assert outcome.reason == "Removes wait constraint"

    @pytest.mark.asyncio
    async def test_reviewer_unavailable_returns_unused(self):
        mock_session = _make_async_session_ctx()
        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.workflows._instruction_review.resolve_agent",
                new_callable=AsyncMock,
                side_effect=Exception("Agent not found"),
            ),
        ):
            outcome = await review_instruction_edit(
                old_instructions="Old instructions.",
                new_instructions="New instructions.",
                change_reason="Testing.",
            )

            assert outcome.used is False
            assert outcome.decision is None

    @pytest.mark.asyncio
    async def test_unparseable_response_returns_unused(self):
        mock_session = _make_async_session_ctx()
        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.workflows._instruction_review.resolve_agent",
                new_callable=AsyncMock,
                return_value=_FakeResolved(agent=_FakeAgent()),
            ),
            patch(
                "app.workflows._instruction_review.inject_agent_mandates",
                new_callable=AsyncMock,
                return_value=_FakeMandate(),
            ),
            patch(
                "app.workflows._instruction_review.complete_internal",
                new_callable=AsyncMock,
                return_value=_FakeCompletionResult(content="not valid json"),
            ),
        ):
            outcome = await review_instruction_edit(
                old_instructions="Old.",
                new_instructions="New.",
                change_reason="Test.",
            )

            assert outcome.used is False
            assert outcome.raw_content == "not valid json"


# ── write_heartbeat_instructions with review gate ──


class TestWriteHeartbeatInstructionsReviewGate:
    """Test that the write function respects supervisor review decisions."""

    @pytest.mark.asyncio
    async def test_rejected_edit_does_not_persist(self):
        from app.services.tools._executor_persona import write_heartbeat_instructions

        reject_outcome = InstructionReviewOutcome(
            decision="reject",
            reason="Removes safety constraint",
            session_id="rev-session",
            reviewer_agent_slug="supervisor",
            reviewer_model_id="claude-sonnet-4-6",
            used=True,
        )
        mock_set = AsyncMock()
        mock_session = _make_async_session_ctx()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=AsyncMock(version=1),
            ),
            patch(
                "app.services.persona_instruction_service.get_persona_heartbeat_instructions",
                new_callable=AsyncMock,
                return_value="Always wait and verify before acting.",
            ),
            patch(
                "app.services.persona_instruction_service.set_persona_heartbeat_instructions",
                new=mock_set,
            ),
            patch(
                "app.workflows._instruction_review.review_instruction_edit",
                new_callable=AsyncMock,
                return_value=reject_outcome,
            ),
        ):
            result = await write_heartbeat_instructions(
                "Act immediately.", "Be faster"
            )

            assert "REJECTED" in result
            assert "Removes safety constraint" in result
            mock_set.assert_not_called()

    @pytest.mark.asyncio
    async def test_approved_edit_persists(self):
        from app.services.tools._executor_persona import write_heartbeat_instructions

        approve_outcome = InstructionReviewOutcome(
            decision="approve",
            reason="Safe addition",
            session_id="rev-session",
            reviewer_agent_slug="supervisor",
            reviewer_model_id="claude-sonnet-4-6",
            used=True,
        )
        mock_set = AsyncMock()
        mock_session = _make_async_session_ctx()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=AsyncMock(version=1),
            ),
            patch(
                "app.services.persona_instruction_service.get_persona_heartbeat_instructions",
                new_callable=AsyncMock,
                return_value="Monitor before acting.",
            ),
            patch(
                "app.services.persona_instruction_service.set_persona_heartbeat_instructions",
                new=mock_set,
            ),
            patch(
                "app.workflows._instruction_review.review_instruction_edit",
                new_callable=AsyncMock,
                return_value=approve_outcome,
            ),
        ):
            result = await write_heartbeat_instructions(
                "Monitor before acting. Also log observations.", "Better observability"
            )

            assert "updated" in result
            assert "supervisor-approved" in result
            mock_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_reviewer_unavailable_still_writes(self):
        from app.services.tools._executor_persona import write_heartbeat_instructions

        unavailable_outcome = InstructionReviewOutcome(
            decision=None,
            reason=None,
            session_id=None,
            reviewer_agent_slug="supervisor",
            reviewer_model_id=None,
            used=False,
        )
        mock_set = AsyncMock()
        mock_session = _make_async_session_ctx()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=AsyncMock(version=1),
            ),
            patch(
                "app.services.persona_instruction_service.get_persona_heartbeat_instructions",
                new_callable=AsyncMock,
                return_value="Old instructions.",
            ),
            patch(
                "app.services.persona_instruction_service.set_persona_heartbeat_instructions",
                new=mock_set,
            ),
            patch(
                "app.workflows._instruction_review.review_instruction_edit",
                new_callable=AsyncMock,
                return_value=unavailable_outcome,
            ),
        ):
            result = await write_heartbeat_instructions(
                "New instructions here.", "Testing"
            )

            assert "updated" in result
            assert "supervisor-approved" not in result
            mock_set.assert_called_once()

    @pytest.mark.asyncio
    async def test_revise_decision_does_not_persist(self):
        from app.services.tools._executor_persona import write_heartbeat_instructions

        revise_outcome = InstructionReviewOutcome(
            decision="revise",
            reason="Weakens monitoring behavior",
            session_id="rev-session",
            reviewer_agent_slug="supervisor",
            reviewer_model_id="claude-sonnet-4-6",
            used=True,
        )
        mock_set = AsyncMock()
        mock_session = _make_async_session_ctx()

        with (
            patch("app.db.async_session", return_value=mock_session),
            patch(
                "app.services.persona_service.get_or_create_persona",
                new_callable=AsyncMock,
                return_value=AsyncMock(version=1),
            ),
            patch(
                "app.services.persona_instruction_service.get_persona_heartbeat_instructions",
                new_callable=AsyncMock,
                return_value="Always monitor active sessions carefully.",
            ),
            patch(
                "app.services.persona_instruction_service.set_persona_heartbeat_instructions",
                new=mock_set,
            ),
            patch(
                "app.workflows._instruction_review.review_instruction_edit",
                new_callable=AsyncMock,
                return_value=revise_outcome,
            ),
        ):
            result = await write_heartbeat_instructions(
                "Check sessions occasionally.", "Less overhead"
            )

            assert "REVISION" in result
            assert "Weakens monitoring behavior" in result
            mock_set.assert_not_called()
