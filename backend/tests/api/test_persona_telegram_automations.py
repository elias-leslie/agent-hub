"""Legacy Telegram automation writers must use central Automations."""

from __future__ import annotations


def test_telegram_automation_creation_is_retired(api_client, mock_db_session):
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

    assert response.status_code == 409
    assert "/automations?project_id=agent-hub" in response.json()["hint"]
    mock_db_session.commit.assert_not_awaited()


def test_telegram_automation_trigger_is_retired(api_client, mock_db_session):
    response = api_client.post("/api/persona/automations/job-telegram/trigger")

    assert response.status_code == 409
    assert "/automations?project_id=agent-hub" in response.json()["hint"]
    mock_db_session.commit.assert_not_awaited()
