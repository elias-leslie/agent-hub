from __future__ import annotations

from app.services.memory.applicability import (
    applicability_has_exclusions,
    applicability_has_targets,
    applicability_matches,
    normalize_applicability,
    normalize_trigger_phases,
    normalize_trigger_task_types,
)
from app.services.memory.memory_models import MemoryApplicability


def test_surface_target_is_normalized_and_detected() -> None:
    applicability = normalize_applicability(
        {"consumer_surfaces": [" codex ", "codex", "claude_code"]}
    )

    assert applicability.consumer_surfaces == ["codex", "claude_code"]
    assert applicability_has_targets(applicability) is True


def test_surface_target_and_exclusion_match_without_overloading_agent_slug() -> None:
    applicability = MemoryApplicability(
        consumer_surfaces=["codex", "claude_code"],
        exclude_consumer_surfaces=["claude_code"],
        agent_slugs=["reviewer"],
    )

    assert applicability_matches(
        applicability,
        consumer_surface="codex",
        consumer_agent_slug="reviewer",
    )
    assert not applicability_matches(
        applicability,
        consumer_surface="pi",
        consumer_agent_slug="reviewer",
    )
    assert not applicability_matches(
        applicability,
        consumer_surface="claude_code",
        consumer_agent_slug="reviewer",
    )
    assert not applicability_matches(
        applicability,
        consumer_surface="codex",
        consumer_agent_slug="other-agent",
    )
    assert applicability_has_exclusions(applicability) is True


def test_tui_aliases_case_and_camel_case_are_normalized() -> None:
    applicability = normalize_applicability(
        {
            "consumer_surfaces": ["Claude", "claude-gpt", "PI-Mono"],
            "consumer_profiles": ["AgentStartup"],
            "agent_slugs": ["Code_Reviewer"],
        }
    )

    assert applicability.consumer_surfaces == ["claude_code", "pi"]
    assert applicability.consumer_profiles == ["agent_startup"]
    assert applicability.agent_slugs == ["code-reviewer"]
    assert applicability_matches(
        applicability,
        consumer_surface="CLAUDE-CODE",
        consumer_profile="agent-startup",
        consumer_agent_slug="code_reviewer",
    )


def test_trigger_identifiers_normalize_session_hook_variants() -> None:
    assert normalize_trigger_task_types(["CodeReview", "Migrations"]) == [
        "code_review",
        "database",
    ]
    assert normalize_trigger_phases(["BeforeAgent", "SessionStart"]) == [
        "before_agent",
        "session_start",
    ]
