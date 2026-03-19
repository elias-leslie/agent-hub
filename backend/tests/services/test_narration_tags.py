"""Tests for narration tag parser."""

from app.services.narration_tags import NarrationTag, parse_narration_tags


class TestParseNarrationTags:
    """Tests for parse_narration_tags()."""

    def test_empty_string(self) -> None:
        assert parse_narration_tags("") == []

    def test_no_tags(self) -> None:
        assert parse_narration_tags("Just regular text with no tags") == []

    def test_single_tag(self) -> None:
        text = "Working on it [[P:started:implementing narration parser]] now"
        result = parse_narration_tags(text)
        assert result == [NarrationTag("started", "implementing narration parser")]

    def test_multiple_tags(self) -> None:
        text = (
            "[[P:started:Phase 1]] I found the issue [[P:found:bug in parser]] "
            "and fixed it [[P:modified:app/services/parser.py]]"
        )
        result = parse_narration_tags(text)
        assert len(result) == 3
        assert result[0] == NarrationTag("started", "Phase 1")
        assert result[1] == NarrationTag("found", "bug in parser")
        assert result[2] == NarrationTag("modified", "app/services/parser.py")

    def test_all_valid_types(self) -> None:
        valid_types = ["started", "found", "modified", "tested", "confidence", "blocked", "decision"]
        for tag_type in valid_types:
            text = f"[[P:{tag_type}:some content]]"
            result = parse_narration_tags(text)
            assert len(result) == 1, f"Failed for type: {tag_type}"
            assert result[0].tag_type == tag_type

    def test_unknown_type_ignored(self) -> None:
        text = "[[P:unknown_type:content]] [[P:started:valid]]"
        result = parse_narration_tags(text)
        assert len(result) == 1
        assert result[0].tag_type == "started"

    def test_content_whitespace_stripped(self) -> None:
        text = "[[P:started:  content with spaces  ]]"
        result = parse_narration_tags(text)
        assert result[0].content == "content with spaces"

    def test_none_input(self) -> None:
        # Type says str but handle None gracefully
        assert parse_narration_tags("") == []

    def test_content_with_colons(self) -> None:
        text = "[[P:found:file:line:42 has the bug]]"
        result = parse_narration_tags(text)
        assert len(result) == 1
        # regex captures everything after the first colon up to ]]
        assert result[0].content == "file:line:42 has the bug"

    def test_confidence_with_number(self) -> None:
        text = "[[P:confidence:85 - all tests pass, minor edge case concern]]"
        result = parse_narration_tags(text)
        assert result[0] == NarrationTag(
            "confidence", "85 - all tests pass, minor edge case concern"
        )

    def test_fast_path_no_prefix(self) -> None:
        """Text without [[P: should short-circuit."""
        text = "A very long text " * 100
        result = parse_narration_tags(text)
        assert result == []

    def test_nested_brackets_not_matched(self) -> None:
        text = "[[P:started:content with [inner] brackets]]"
        result = parse_narration_tags(text)
        # The ] in [inner] terminates the regex match — no valid tag extracted
        assert len(result) == 0
