"""Tests for persona document parsing helpers."""

from __future__ import annotations

from app.services.persona_documents import split_legacy_user_context

LEGACY_USER_CONTEXT = """# User Profile: Elias

## Identity
- Name: Elias
- Preferred address: Elias (first name)

## Work Context
- Role: Creator of the system / personal developer
- Built SummitFlow and Agent Hub as dev automation infrastructure

### Roadmap (in order)
1. Monkey Fight
2. Agent Hub

## Communication Style
- Tone: Casual
- Detail: Concise bullet points preferred

## Notification Preferences
- Timezone: EST
- Threshold: Critical failures only

## Working Schedule
- Timezone: EST
- Available for decisions: any time

## Boundaries & Escalation
- No sudo
- Escalate on notable production data loss

## Identity Review
- Name approved
"""


def test_split_legacy_user_context_extracts_profile_and_notes() -> None:
    profile, notes = split_legacy_user_context(LEGACY_USER_CONTEXT)

    assert profile is not None
    assert profile["user_identity"].startswith("- Name: Elias")
    assert "### Roadmap" in profile["work_context"]
    assert profile["communication_style"] == "- Tone: Casual\n- Detail: Concise bullet points preferred"
    assert profile["timezone"] == "America/New_York"
    assert "Timezone:" not in profile["notification_preferences"]
    assert "Timezone:" not in profile["working_schedule"]
    assert notes == "## Identity Review\n- Name approved"


def test_split_legacy_user_context_returns_original_text_when_no_profile_sections() -> None:
    profile, notes = split_legacy_user_context("Jenny should keep responses concise.")

    assert profile is None
    assert notes == "Jenny should keep responses concise."
