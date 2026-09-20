"""Tests for memory export filtering and compact formatter output."""

from __future__ import annotations

import json
from pathlib import Path

from agent_hub_st.memory_batch_export import _export_to_file_or_stdout, _filter_episode_fields
from agent_hub_st.memory_formatters import format_get_compact, format_search_compact


def test_filter_episode_fields_keeps_import_relevant_metadata() -> None:
    filtered = _filter_episode_fields(
        {
            "uuid": "ep-1",
            "content": "Body",
            "category": "reference",
            "injection_tier": "reference",
            "summary": "Summary",
            "pinned": True,
            "trigger_task_types": ["feature"],
            "tags": ["memory"],
            "auto_inject": False,
            "display_order": 7,
            "ignored": "nope",
        },
        full=False,
    )

    assert filtered == {
        "uuid": "ep-1",
        "content": "Body",
        "category": "reference",
        "injection_tier": "reference",
        "summary": "Summary",
        "pinned": True,
        "trigger_task_types": ["feature"],
        "tags": ["memory"],
        "auto_inject": False,
        "display_order": 7,
    }


def test_export_to_file_or_stdout_uses_utc_timestamp(tmp_path: Path) -> None:
    output = tmp_path / "memory.json"

    _export_to_file_or_stdout(output, [{"uuid": "ep-1", "content": "Body"}], full=False)

    payload = json.loads(output.read_text())
    assert payload["count"] == 1
    assert payload["exported_at"].endswith("+00:00")


def test_format_search_compact_shows_tier_summary_and_meta(capsys) -> None:
    format_search_compact(
        {
            "query": "memory",
            "results": [
                {
                    "uuid": "abc12345-dead-beef-cafe-1234567890ab",
                    "category": "guardrail",
                    "summary": "Use compact headers",
                    "relevance_score": 0.92,
                    "pinned": True,
                    "trigger_task_types": ["feature"],
                    "tags": ["memory", "cli"],
                    "content": "**Headers**: Use compact headers.",
                }
            ],
        }
    )

    out = capsys.readouterr().out
    assert "abc12345 [guardrail] 0.92 Use compact headers" in out
    assert "pinned | triggers=feature | tags=memory,cli" in out


def test_format_get_compact_shows_tags(capsys) -> None:
    format_get_compact(
        {
            "uuid": "abc12345-dead-beef-cafe-1234567890ab",
            "injection_tier": "reference",
            "summary": "Compact headers",
            "tags": ["memory", "cli"],
            "content": "**Headers**: Use compact headers.",
        }
    )

    out = capsys.readouterr().out
    assert "Tags: memory, cli" in out
