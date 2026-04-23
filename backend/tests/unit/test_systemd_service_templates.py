from __future__ import annotations

from pathlib import Path

SYSTEMD_DIR = Path(__file__).resolve().parents[3] / "scripts" / "systemd"


def test_split_worker_units_exist_and_combined_template_is_removed() -> None:
    assert not (SYSTEMD_DIR / "agent-hub-hatchet-worker.service").exists()
    assert (SYSTEMD_DIR / "agent-hub-hatchet-agent-worker.service").exists()
    assert (SYSTEMD_DIR / "agent-hub-hatchet-ops-worker.service").exists()


def test_agent_worker_template_points_to_agent_entrypoint_and_host_marker() -> None:
    text = (SYSTEMD_DIR / "agent-hub-hatchet-agent-worker.service").read_text()
    assert "__PROJECT_ROOT__" in text
    assert "ExecStart=__PROJECT_ROOT__/backend/.venv/bin/python -m app.worker_agents" in text
    assert 'Environment="AGENT_HUB_WORKER_ROLE=agents"' in text
    assert 'Environment="AGENT_HUB_HOST_SERVICE=agent-hub-hatchet-agent-worker.service"' in text
    assert "KillMode=control-group" in text


def test_ops_worker_template_points_to_ops_entrypoint_and_host_marker() -> None:
    text = (SYSTEMD_DIR / "agent-hub-hatchet-ops-worker.service").read_text()
    assert "__PROJECT_ROOT__" in text
    assert "ExecStart=__PROJECT_ROOT__/backend/.venv/bin/python -m app.worker_ops" in text
    assert 'Environment="AGENT_HUB_WORKER_ROLE=ops"' in text
    assert 'Environment="AGENT_HUB_HOST_SERVICE=agent-hub-hatchet-ops-worker.service"' in text
    assert "KillMode=control-group" in text


def test_frontend_template_uses_control_group_shutdown() -> None:
    text = (SYSTEMD_DIR / "agent-hub-frontend.service").read_text()
    assert "KillMode=control-group" in text


def test_telegram_bot_template_exists_and_points_to_run_script() -> None:
    text = (SYSTEMD_DIR / "agent-hub-telegram-bot.service").read_text()
    assert "__PROJECT_ROOT__" in text
    assert "WorkingDirectory=__PROJECT_ROOT__/backend" in text
    assert "python -m app.scripts.run_telegram_bot" in text
    assert "KillMode=control-group" in text


def test_telegram_report_service_and_timer_templates_exist() -> None:
    service = (SYSTEMD_DIR / "agent-hub-telegram-status-report.service").read_text()
    timer = (SYSTEMD_DIR / "agent-hub-telegram-status-report.timer").read_text()
    assert "__PROJECT_ROOT__" in service
    assert "python -m app.scripts.send_jenny_telegram_status_report" in service
    assert "OnBootSec=10m" in timer
    assert "OnUnitActiveSec=1h" in timer
    assert "Persistent=true" in timer
