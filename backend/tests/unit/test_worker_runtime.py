from __future__ import annotations

from app.worker_runtime import AGENT_WORKFLOWS, ALL_WORKFLOWS, OPS_WORKFLOWS
from app.workflows.completion import completion_task
from app.workflows.model_sync import model_enrichment_sync_task
from app.workflows.observation import observation_processing_task
from app.workflows.persona_heartbeat import persona_heartbeat_task
from app.workflows.persona_scheduler import persona_scheduler_task
from app.workflows.persona_wake import agent_wake_task
from app.workflows.scheduled import (
    data_retention_task,
    feedback_cleanup_task,
    memory_cleanup_task,
    memory_governance_task,
    session_cleanup_task,
    tier_optimizer_task,
)
from app.workflows.session_reaper import session_reaper_task
from app.workflows.site_health_check import (
    single_project_health_check_task,
    site_health_check_task,
)
from app.workflows.summary import session_summary_task
from app.workflows.webhooks import webhook_delivery_task


def test_agent_workflows_match_long_lived_agent_runtime() -> None:
    assert (
        completion_task,
        persona_heartbeat_task,
        agent_wake_task,
    ) == AGENT_WORKFLOWS


def test_ops_workflows_match_maintenance_runtime() -> None:
    assert (
        persona_scheduler_task,
        session_cleanup_task,
        tier_optimizer_task,
        memory_cleanup_task,
        memory_governance_task,
        feedback_cleanup_task,
        data_retention_task,
        webhook_delivery_task,
        session_summary_task,
        observation_processing_task,
        model_enrichment_sync_task,
        site_health_check_task,
        single_project_health_check_task,
        session_reaper_task,
    ) == OPS_WORKFLOWS


def test_all_workflows_combine_split_workers_without_duplicates() -> None:
    assert ALL_WORKFLOWS == OPS_WORKFLOWS + AGENT_WORKFLOWS
    assert len(ALL_WORKFLOWS) == len(set(ALL_WORKFLOWS))
