"""Who may receive which context: one test per audience rule, across every role.

Roles come only from facts Agent Hub or Tether know (the Aico work role and
Tether's coordinator marking); a session with neither is "unknown" and keeps the
full delivery. The fixtures mirror the live data shapes: coordinator-only
memories, Neri hunters' per-role project prompts, and project-scoped rules.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from app.services.context_policy import ContextPolicy, policy_match
from app.services.memory.applicability import UNKNOWN_ROLE_TAG, applicability_matches
from app.services.memory.memory_models import (
    MemoryApplicability,
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.runtime_context import _forced_memory_item_matches
from app.services.session_roles import WORK_ROLES

COORDINATOR_ONLY = MemoryApplicability(
    audience_tags=["aico-coordinator", "work-role:coordinator", UNKNOWN_ROLE_TAG]
)
# Every consumer shape a delivery can carry: each declared role, Tether's
# coordinator marking alone or with a role, and no role at all.
CONSUMERS: dict[str, list[str]] = {
    **{role: [f"work-role:{role}"] for role in WORK_ROLES},
    "tether-coordinator": ["aico-coordinator"],
    "tether-coordinator+coordinator-role": ["aico-coordinator", "work-role:coordinator"],
    "unknown": [],
}
COORDINATOR_CONSUMERS = {"coordinator", "tether-coordinator", "tether-coordinator+coordinator-role"}
PROJECTS = ["summitflow", "aico", "agent-hub", "neri", "neri-hunters"]


def _context(project: str, tags: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        project_id=project,
        agent_slug=None,
        consumer_surface="claude_code",
        consumer_profile="agent_startup",
        consumer_tags=tags,
        workflow_ids=[],
        task_type=None,
        phase=None,
    )


@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_coordinator_only_content_reaches_coordinators_and_unknown_roles_only(consumer: str) -> None:
    expected = consumer in COORDINATOR_CONSUMERS or consumer == "unknown"
    assert applicability_matches(COORDINATOR_ONLY, consumer_tags=CONSUMERS[consumer]) is expected


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_hunter_content_reaches_hunters_in_neri_hunters_only(consumer: str, project: str) -> None:
    hunter_prompt = ContextPolicy(
        scope="project",
        targets=["neri-hunters"],
        applicability={"audience_tags": ["work-role:hunting"]},
    )
    matched, _reason = policy_match(hunter_prompt, _context(project, CONSUMERS[consumer]))
    assert matched is (consumer == "hunting" and project == "neri-hunters")


@pytest.mark.parametrize("project", PROJECTS)
@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_project_prompt_reaches_only_that_project(consumer: str, project: str) -> None:
    project_prompt = ContextPolicy(scope="project", targets=["agent-hub"])
    matched, _reason = policy_match(project_prompt, _context(project, CONSUMERS[consumer]))
    assert matched is (project == "agent-hub")


@pytest.mark.parametrize("project", [*PROJECTS, None])
@pytest.mark.parametrize("consumer", sorted(CONSUMERS))
def test_project_memory_reaches_only_that_project(consumer: str, project: str | None) -> None:
    memory = MemorySearchResult(
        uuid="neri-rule",
        content="neri-rule",
        source=MemorySource.SYSTEM,
        relevance_score=1.0,
        created_at=datetime.now(UTC),
        scope=MemoryScope.PROJECT,
        scope_id="neri",
        category=MemoryCategory.GUARDRAIL,
    )
    assert _forced_memory_item_matches(
        memory,
        project_id=project,
        include_global=True,
        include_mandates=True,
        include_guardrails=True,
        include_references=True,
        exclude_tags=[],
        exclude_memory_uuids=[],
        consumer_surface="claude_code",
        consumer_profile="agent_startup",
        consumer_agent_slug=None,
        consumer_tags=CONSUMERS[consumer],
    ) is (project == "neri")


def test_a_session_cannot_name_itself_unknown_or_an_unregistered_role() -> None:
    # A forged unknown tag next to a declared role, or an unregistered role,
    # never unlocks coordinator-only content.
    assert not applicability_matches(COORDINATOR_ONLY, consumer_tags=[UNKNOWN_ROLE_TAG, "work-role:review"])
    hunter_only = MemoryApplicability(audience_tags=["work-role:hunting"])
    assert not applicability_matches(hunter_only, consumer_tags=["work-role:hunter"])
