"""Tests for st memory seed CLI command.

Covers:
- _parse_frontmatter() YAML parsing and body extraction
- _build_skill_tag() tag generation
- _find_existing_by_tag() episode search
- _upsert_skill_episode() create/update/unchanged logic
- seed_impl() directory processing and dry-run
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
import typer
from agent_hub_st.memory_seed import (
    _build_skill_tag,
    _find_existing_by_tag,
    _parse_frontmatter,
    _upsert_skill_episode,
    seed_impl,
)


class TestParseFrontmatter:
    """Tests for _parse_frontmatter YAML parsing."""

    def test_parse_frontmatter_extracts_yaml_metadata(self) -> None:
        """Test that frontmatter extracts tier, summary, tags from YAML."""
        text = """---
tier: guardrail
summary: Test skill
tags: [skill:test, autocode]
---

# Test Content
This is the body."""

        frontmatter, body = _parse_frontmatter(text)

        assert frontmatter["tier"] == "guardrail"
        assert frontmatter["summary"] == "Test skill"
        assert frontmatter["tags"] == ["skill:test", "autocode"]
        assert body == "# Test Content\nThis is the body."

    def test_parse_frontmatter_handles_trigger_task_types_list(self) -> None:
        """Test that frontmatter handles trigger_task_types as list."""
        text = """---
trigger_task_types: [feature, refactor, bug]
---

Content here."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["trigger_task_types"] == ["feature", "refactor", "bug"]

    def test_parse_frontmatter_handles_boolean_true(self) -> None:
        """Test that frontmatter parses pinned: true correctly."""
        text = """---
pinned: true
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["pinned"]

    def test_parse_frontmatter_handles_boolean_false(self) -> None:
        """Test that frontmatter parses pinned: false correctly."""
        text = """---
pinned: false
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert not frontmatter["pinned"]

    def test_parse_frontmatter_handles_yes_no_booleans(self) -> None:
        """Test that frontmatter recognizes yes/no as boolean values."""
        text = """---
enabled: yes
disabled: no
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["enabled"]
        assert not frontmatter["disabled"]

    def test_parse_frontmatter_returns_body_without_frontmatter(self) -> None:
        """Test that body content excludes frontmatter delimiters."""
        text = """---
tier: reference
---

# Main Content

This is the actual body text that should be returned."""

        _frontmatter, body = _parse_frontmatter(text)

        assert "---" not in body
        assert "tier:" not in body
        assert body.startswith("# Main Content")

    def test_parse_frontmatter_returns_empty_dict_without_frontmatter(self) -> None:
        """Test that files without frontmatter return empty dict."""
        text = """# Regular Markdown

No frontmatter here."""

        _frontmatter, body = _parse_frontmatter(text)

        assert _frontmatter == {}
        assert body == text

    def test_parse_frontmatter_handles_incomplete_frontmatter(self) -> None:
        """Test that incomplete frontmatter (only one ---) is ignored."""
        text = """---
tier: guardrail

# Content without closing delimiter"""

        _frontmatter, body = _parse_frontmatter(text)

        assert _frontmatter == {}
        assert body == text

    def test_parse_frontmatter_ignores_comments(self) -> None:
        """Test that YAML comments are ignored during parsing."""
        text = """---
# This is a comment
tier: guardrail
# Another comment
summary: Test
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["tier"] == "guardrail"
        assert frontmatter["summary"] == "Test"
        assert "#" not in frontmatter

    def test_parse_frontmatter_handles_quoted_strings(self) -> None:
        """Test that quoted strings are properly unquoted."""
        text = """---
summary: 'Single quoted'
description: "Double quoted"
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["summary"] == "Single quoted"
        assert frontmatter["description"] == "Double quoted"

    def test_parse_frontmatter_handles_empty_list(self) -> None:
        """Test that empty lists are parsed correctly."""
        text = """---
tags: []
trigger_task_types: []
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["tags"] == []
        assert frontmatter["trigger_task_types"] == []

    def test_parse_frontmatter_handles_numeric_values(self) -> None:
        """Test that numeric values are parsed as integers."""
        text = """---
priority: 10
confidence: 90
---

Body content."""

        frontmatter, _body = _parse_frontmatter(text)

        assert frontmatter["priority"] == 10
        assert frontmatter["confidence"] == 90
        assert isinstance(frontmatter["priority"], int)

    def test_parse_frontmatter_handles_multiline_content(self) -> None:
        """Test that body with multiple lines is preserved."""
        text = """---
tier: guardrail
---

# Section 1

Content line 1.
Content line 2.

## Section 2

More content."""

        _frontmatter, body = _parse_frontmatter(text)

        assert "# Section 1" in body
        assert "## Section 2" in body
        assert "Content line 1." in body


class TestBuildSkillTag:
    """Tests for _build_skill_tag tag generation."""

    def test_build_skill_tag_creates_tag_from_filename(self) -> None:
        """Test that skill tag is created from filename stem."""
        tag = _build_skill_tag("autocode-guidelines.md")

        assert tag == "skill:autocode-guidelines"

    def test_build_skill_tag_removes_extension(self) -> None:
        """Test that file extension is removed from tag."""
        tag = _build_skill_tag("memory-management.md")

        assert tag == "skill:memory-management"
        assert ".md" not in tag

    def test_build_skill_tag_handles_path_object(self) -> None:
        """Test that Path objects are handled correctly."""
        path = Path("/home/user/skills/test-skill.md")
        tag = _build_skill_tag(path.name)

        assert tag == "skill:test-skill"

    def test_build_skill_tag_preserves_hyphens(self) -> None:
        """Test that hyphens in filename are preserved."""
        tag = _build_skill_tag("quality-gate-rules.md")

        assert tag == "skill:quality-gate-rules"


class TestFindExistingByTag:
    """Tests for _find_existing_by_tag episode search."""

    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_find_existing_by_tag_returns_episode_when_found(self, mock_request: MagicMock) -> None:
        """Test that existing episode is returned when tag matches."""
        mock_request.return_value = {
            "results": [
                {
                    "uuid": "ep-123",
                    "content": "Test content",
                    "tags": ["skill:test", "autocode"],
                }
            ]
        }

        result = _find_existing_by_tag("skill:test", "global", None)

        assert result is not None
        assert result["uuid"] == "ep-123"
        mock_request.assert_called_once_with(
            "GET",
            "/api/memory/search",
            params={"query": "skill:test", "limit": 5},
            scope="global",
            scope_id=None,
            tool_name="st memory seed",
        )

    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_find_existing_by_tag_returns_none_when_not_found(self, mock_request: MagicMock) -> None:
        """Test that None is returned when no matching episode exists."""
        mock_request.return_value = {"results": []}

        result = _find_existing_by_tag("skill:missing", "global", None)

        assert result is None

    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_find_existing_by_tag_filters_by_exact_tag_match(self, mock_request: MagicMock) -> None:
        """Test that only episodes with exact tag match are returned."""
        mock_request.return_value = {
            "results": [
                {"uuid": "ep-1", "tags": ["skill:other"]},
                {"uuid": "ep-2", "tags": ["skill:test", "autocode"]},
            ]
        }

        result = _find_existing_by_tag("skill:test", "global", None)

        assert result is not None
        assert result["uuid"] == "ep-2"

    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_find_existing_by_tag_handles_api_errors(self, mock_request: MagicMock) -> None:
        """Test that API errors are handled gracefully."""
        mock_request.side_effect = Exception("API error")

        result = _find_existing_by_tag("skill:test", "global", None)

        assert result is None

    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_find_existing_by_tag_passes_scope_parameters(self, mock_request: MagicMock) -> None:
        """Test that scope and scope_id are passed to API."""
        mock_request.return_value = {"results": []}

        _find_existing_by_tag("skill:test", "project", "test-project")

        mock_request.assert_called_once_with(
            "GET",
            "/api/memory/search",
            params={"query": "skill:test", "limit": 5},
            scope="project",
            scope_id="test-project",
            tool_name="st memory seed",
        )


class TestUpsertSkillEpisode:
    """Tests for _upsert_skill_episode create/update logic."""

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_creates_new_episode(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that new episode is created when none exists."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {
            "tier": "guardrail",
            "summary": "Test skill",
            "tags": ["autocode"],
        }

        action = _upsert_skill_episode(
            "skill:test", "Test content", frontmatter, "global", None, dry_run=False
        )

        assert action == "created"
        mock_request.assert_called_once()
        call_args = mock_request.call_args
        assert call_args[0] == ("POST", "/api/memory/save-learning")
        assert call_args[1]["json"]["content"] == "Test content"
        assert call_args[1]["json"]["injection_tier"] == "guardrail"
        assert "tags" not in call_args[1]["json"]
        mock_replace_tags.assert_called_once_with("ep-123", ["autocode", "skill:test"])

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.fetch_episode_tags")
    @patch("agent_hub_st.memory_seed.fetch_existing_episode")
    def test_upsert_skill_episode_returns_unchanged_for_identical_content(
        self,
        mock_fetch_existing: MagicMock,
        mock_fetch_tags: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """Test that unchanged is returned when content matches."""
        mock_find.return_value = {
            "uuid": "ep-123",
        }
        mock_fetch_existing.return_value = {
            "uuid": "ep-123",
            "content": "Test content",
            "summary": "skill:test",
            "injection_tier": "reference",
            "trigger_task_types": [],
            "pinned": False,
        }
        mock_fetch_tags.return_value = ["skill:test"]
        frontmatter: dict[str, Any] = {}

        action = _upsert_skill_episode(
            "skill:test", "Test content", frontmatter, "global", None, dry_run=False
        )

        assert action == "unchanged"
        mock_fetch_existing.assert_called_once_with("ep-123")
        mock_fetch_tags.assert_called_once_with("ep-123")

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.patch_episode_properties")
    @patch("agent_hub_st.memory_seed.update_episode_content_or_tier")
    @patch("agent_hub_st.memory_seed.fetch_episode_tags")
    @patch("agent_hub_st.memory_seed.fetch_existing_episode")
    def test_upsert_skill_episode_updates_when_content_differs(
        self,
        mock_fetch_existing: MagicMock,
        mock_fetch_tags: MagicMock,
        mock_update_episode: MagicMock,
        mock_patch_properties: MagicMock,
        mock_replace_tags: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """Test that episode is updated when content changes."""
        mock_find.return_value = {
            "uuid": "ep-123",
        }
        mock_fetch_existing.return_value = {
            "uuid": "ep-123",
            "content": "Old content",
            "summary": "skill:test",
            "injection_tier": "reference",
            "trigger_task_types": [],
            "pinned": False,
        }
        mock_fetch_tags.return_value = ["skill:test"]
        frontmatter: dict[str, Any] = {}

        action = _upsert_skill_episode(
            "skill:test", "New content", frontmatter, "global", None, dry_run=False
        )

        assert action == "updated"
        mock_update_episode.assert_called_once_with(
            "ep-123",
            content="New content",
            tier="reference",
        )
        mock_patch_properties.assert_not_called()
        mock_replace_tags.assert_not_called()

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_dry_run_prevents_writes(
        self, mock_request: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that dry_run=True previews without writing."""
        mock_find.return_value = None
        frontmatter: dict[str, Any] = {}

        action = _upsert_skill_episode(
            "skill:test", "Test content", frontmatter, "global", None, dry_run=True
        )

        assert action == "would_create"
        mock_request.assert_not_called()

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.fetch_episode_tags")
    @patch("agent_hub_st.memory_seed.fetch_existing_episode")
    def test_upsert_skill_episode_dry_run_shows_would_update(
        self,
        mock_fetch_existing: MagicMock,
        mock_fetch_tags: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """Test that dry_run shows would_update for changed content."""
        mock_find.return_value = {
            "uuid": "ep-123",
        }
        mock_fetch_existing.return_value = {
            "uuid": "ep-123",
            "content": "Old content",
            "summary": "skill:test",
            "injection_tier": "reference",
            "trigger_task_types": [],
            "pinned": False,
        }
        mock_fetch_tags.return_value = ["skill:test"]
        frontmatter: dict[str, Any] = {}

        action = _upsert_skill_episode(
            "skill:test", "New content", frontmatter, "global", None, dry_run=True
        )

        assert action == "would_update"
        mock_fetch_existing.assert_called_once_with("ep-123")
        mock_fetch_tags.assert_called_once_with("ep-123")

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_merges_skill_tag_with_frontmatter_tags(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that skill tag is merged with frontmatter tags."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {
            "tags": ["autocode", "quality"],
        }

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        mock_replace_tags.assert_called_once_with("ep-123", ["autocode", "quality", "skill:test"])

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_uses_default_tier_reference(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that default tier is reference when not specified."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {}

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert call_args[1]["json"]["injection_tier"] == "reference"

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_includes_trigger_task_types_when_present(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that trigger_task_types are included in payload."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {
            "trigger_task_types": ["feature", "refactor"],
        }

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert call_args[1]["json"]["trigger_task_types"] == ["feature", "refactor"]

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_includes_pinned_when_true(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that pinned flag is included when true."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {
            "pinned": True,
        }

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert call_args[1]["json"]["pinned"]

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_omits_pinned_when_false(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that pinned is omitted from payload when false."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {
            "pinned": False,
        }

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert "pinned" not in call_args[1]["json"]

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_uses_skill_tag_as_default_summary(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that skill tag is used as summary when not provided."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {}

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert call_args[1]["json"]["summary"] == "skill:test"

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.agent_hub_request")
    def test_upsert_skill_episode_sets_confidence_to_90(
        self, mock_request: MagicMock, mock_replace_tags: MagicMock, mock_find: MagicMock
    ) -> None:
        """Test that confidence is set to 90 for seeded episodes."""
        mock_find.return_value = None
        mock_request.return_value = {"uuid": "ep-123"}
        frontmatter: dict[str, Any] = {}

        _upsert_skill_episode(
            "skill:test", "Content", frontmatter, "global", None, dry_run=False
        )

        call_args = mock_request.call_args
        assert call_args[1]["json"]["confidence"] == 90

    @patch("agent_hub_st.memory_seed._find_existing_by_tag")
    @patch("agent_hub_st.memory_seed.replace_episode_tags")
    @patch("agent_hub_st.memory_seed.patch_episode_properties")
    @patch("agent_hub_st.memory_seed.update_episode_content_or_tier")
    @patch("agent_hub_st.memory_seed.fetch_episode_tags")
    @patch("agent_hub_st.memory_seed.fetch_existing_episode")
    def test_upsert_skill_episode_updates_metadata_without_recreating(
        self,
        mock_fetch_existing: MagicMock,
        mock_fetch_tags: MagicMock,
        mock_update_episode: MagicMock,
        mock_patch_properties: MagicMock,
        mock_replace_tags: MagicMock,
        mock_find: MagicMock,
    ) -> None:
        """Metadata-only changes should patch the existing episode in place."""
        mock_find.return_value = {"uuid": "ep-123"}
        mock_fetch_existing.return_value = {
            "uuid": "ep-123",
            "content": "Content",
            "summary": "Old summary",
            "injection_tier": "reference",
            "trigger_task_types": ["bug"],
            "pinned": False,
        }
        mock_fetch_tags.return_value = ["skill:test"]

        action = _upsert_skill_episode(
            "skill:test",
            "Content",
            {
                "summary": "Fresh summary",
                "trigger_task_types": ["feature", "refactor"],
                "pinned": True,
                "tags": ["quality"],
            },
            "global",
            None,
            dry_run=False,
        )

        assert action == "updated"
        mock_update_episode.assert_not_called()
        mock_patch_properties.assert_called_once_with(
            "ep-123",
            "Fresh summary",
            "feature,refactor",
            None,
            True,
            None,
            None,
        )
        mock_replace_tags.assert_called_once_with("ep-123", ["quality", "skill:test"])


class TestSeedImpl:
    """Tests for seed_impl directory processing."""

    @patch("agent_hub_st.memory_seed.typer")
    def test_seed_impl_exits_when_directory_not_found(
        self, mock_typer: MagicMock, tmp_path: Path
    ) -> None:
        """Test that seed_impl exits when directory does not exist."""
        mock_typer.Exit = typer.Exit
        missing_dir = tmp_path / "missing"

        with pytest.raises(typer.Exit):
            seed_impl(missing_dir, "global", None, dry_run=False, project=None)

    @patch("agent_hub_st.memory_seed.typer")
    def test_seed_impl_exits_when_path_is_not_directory(
        self, mock_typer: MagicMock, tmp_path: Path
    ) -> None:
        """Test that seed_impl exits when path is a file not directory."""
        mock_typer.Exit = typer.Exit
        file_path = tmp_path / "file.txt"
        file_path.write_text("test")

        with pytest.raises(typer.Exit):
            seed_impl(file_path, "global", None, dry_run=False, project=None)

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_reads_all_md_files_from_directory(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that all .md files are processed from directory."""
        # Create test files
        (tmp_path / "skill1.md").write_text("---\ntier: guardrail\n---\nContent 1")
        (tmp_path / "skill2.md").write_text("---\ntier: reference\n---\nContent 2")
        (tmp_path / "readme.txt").write_text("Not a markdown file")
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        assert mock_upsert.call_count == 2

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_dry_run_previews_without_writing(
        self, mock_upsert: MagicMock, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Test that dry_run=True passes through to upsert."""
        (tmp_path / "test.md").write_text("---\ntier: guardrail\n---\nContent")
        mock_upsert.return_value = "would_create"

        seed_impl(tmp_path, "global", None, dry_run=True, project=None)

        mock_upsert.assert_called_once()
        # dry_run is 6th positional argument (index 5)
        assert mock_upsert.call_args[0][5]
        out = capsys.readouterr().out
        assert "WOULD_CREATE test.md" in out
        assert "Dry run complete: 1 created, 0 updated, 0 unchanged, 0 failed" in out

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_skips_files_with_empty_body(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that files with empty body are skipped."""
        (tmp_path / "empty.md").write_text("---\ntier: guardrail\n---\n\n")
        (tmp_path / "valid.md").write_text("---\ntier: guardrail\n---\nContent")
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        assert mock_upsert.call_count == 1

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_handles_upsert_errors_gracefully(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that errors during upsert are caught and counted."""
        (tmp_path / "fail.md").write_text("---\ntier: guardrail\n---\nContent")
        (tmp_path / "success.md").write_text("---\ntier: guardrail\n---\nContent")
        mock_upsert.side_effect = [Exception("API error"), "created"]

        # Should not raise, but continue processing
        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        assert mock_upsert.call_count == 2

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_uses_project_scope_when_project_provided(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that project parameter sets scope and scope_id."""
        (tmp_path / "test.md").write_text("---\ntier: guardrail\n---\nContent")
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project="test-project")

        mock_upsert.assert_called_once()
        assert mock_upsert.call_args[0][3] == "project"
        assert mock_upsert.call_args[0][4] == "test-project"

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_processes_files_in_sorted_order(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that files are processed in sorted order."""
        (tmp_path / "c.md").write_text("---\n---\nContent C")
        (tmp_path / "a.md").write_text("---\n---\nContent A")
        (tmp_path / "b.md").write_text("---\n---\nContent B")
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        calls = [call[0][0] for call in mock_upsert.call_args_list]
        assert calls == ["skill:a", "skill:b", "skill:c"]

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_idempotent_reseeding_produces_no_changes(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that re-seeding same content produces unchanged results."""
        (tmp_path / "test.md").write_text("---\ntier: guardrail\n---\nContent")
        mock_upsert.return_value = "unchanged"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        mock_upsert.assert_called_once()

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_passes_frontmatter_tags_to_upsert(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that frontmatter tags are passed to upsert."""
        (tmp_path / "test.md").write_text(
            "---\ntags: [autocode, quality]\n---\nContent"
        )
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        frontmatter = mock_upsert.call_args[0][2]
        assert frontmatter["tags"] == ["autocode", "quality"]

    @patch("agent_hub_st.memory_seed._upsert_skill_episode")
    def test_seed_impl_handles_files_without_frontmatter(
        self, mock_upsert: MagicMock, tmp_path: Path
    ) -> None:
        """Test that files without frontmatter are processed with defaults."""
        (tmp_path / "no-frontmatter.md").write_text("# Just content\n\nNo YAML.")
        mock_upsert.return_value = "created"

        seed_impl(tmp_path, "global", None, dry_run=False, project=None)

        frontmatter = mock_upsert.call_args[0][2]
        assert frontmatter == {}
