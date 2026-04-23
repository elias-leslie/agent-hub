from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from app.models.persona_scheduled_job import PersonaScheduledJob

from .test_persona import _make_persona


class TestPersonaTelegramAutomations:
    def test_creates_persona_automation_with_telegram_delivery(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        next_run = datetime(2026, 4, 16, 14, 0, tzinfo=UTC)

        async def _refresh(job: PersonaScheduledJob) -> None:
            job.id = "job-created"
            if job.created_at is None:
                job.created_at = datetime(2026, 4, 15, 14, 0, tzinfo=UTC)

        mock_db_session.refresh = _refresh

        with (
            patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)),
            patch("app.api.persona.automations.compute_next_run", return_value=next_run),
        ):
            response = api_client.post(
                "/api/persona/automations",
                json={
                    "name": "Telegram status",
                    "schedule_type": "every",
                    "schedule_value": "3600000",
                    "schedule_timezone": "UTC",
                    "payload_type": "agent_turn",
                    "payload_message": "Check active work and send Telegram status.",
                    "delivery": "telegram",
                },
            )

        assert response.status_code == 201
        assert response.json()["delivery"] == "telegram"
        added_job = mock_db_session.add.call_args.args[0]
        assert added_job.delivery == "telegram"

    def test_rejects_telegram_delivery_for_non_agent_turn_payload(self, api_client, mock_db_session):
        persona = _make_persona(id=7)

        with patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)):
            response = api_client.post(
                "/api/persona/automations",
                json={
                    "name": "Bad telegram push",
                    "schedule_type": "every",
                    "schedule_value": "3600000",
                    "schedule_timezone": "UTC",
                    "payload_type": "push",
                    "payload_message": "Push only",
                    "delivery": "telegram",
                },
            )

        assert response.status_code == 422

    def test_trigger_automation_calls_telegram_delivery_helper(self, api_client, mock_db_session):
        persona = _make_persona(id=7)
        job = PersonaScheduledJob(
            id="job-telegram",
            persona_id=7,
            name="Immediate Telegram status",
            schedule_type="every",
            schedule_value="3600000",
            schedule_timezone="UTC",
            payload_type="agent_turn",
            payload_message="Send Telegram status.",
            delivery="telegram",
            enabled=True,
            run_count=2,
            created_at=datetime(2026, 4, 10, 9, 0, tzinfo=UTC),
        )
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = job
        mock_db_session.execute.return_value = mock_result

        with (
            patch("app.api.persona.automations.get_or_create_persona", new=AsyncMock(return_value=persona)),
            patch(
                "app.api.persona.automations.execute_job",
                new=AsyncMock(return_value=MagicMock(output="Triggered", session_id="sess-123")),
            ),
            patch(
                "app.api.persona.automations._maybe_send_delivery_telegram",
                new=AsyncMock(),
            ) as mock_telegram,
            patch(
                "app.api.persona.automations.compute_next_run",
                return_value=datetime(2026, 4, 16, 9, 0, tzinfo=UTC),
            ),
        ):
            response = api_client.post("/api/persona/automations/job-telegram/trigger")

        assert response.status_code == 200
        mock_telegram.assert_awaited_once_with(job, "Triggered")
