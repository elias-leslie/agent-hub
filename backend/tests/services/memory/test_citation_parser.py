"""Tests for citation parser module."""

import pytest

from app.services.memory.citation_parser import (
    Citation,
    CitationType,
    ParseResult,
    extract_feedback_tags,
    extract_summary_tags,
    extract_uuid_prefixes,
    format_citation,
    format_guardrail_citation,
    format_mandate_citation,
    format_reference_citation,
    parse_citations,
    parse_feedback_tags,
    parse_summary_tags,
)


@pytest.mark.unit
class TestParseCitations:
    """Tests for parse_citations function."""

    def test_parses_single_mandate_citation(self):
        """Test parsing a single mandate citation."""
        text = "Per [M:abc12345], we should use async."
        result = parse_citations(text)

        assert len(result.citations) == 1
        assert result.citations[0].type == CitationType.MANDATE
        assert result.citations[0].uuid_prefix == "abc12345"
        assert result.mandate_count == 1
        assert result.guardrail_count == 0

    def test_parses_single_guardrail_citation(self):
        """Test parsing a single guardrail citation."""
        text = "This violates [G:def67890]."
        result = parse_citations(text)

        assert len(result.citations) == 1
        assert result.citations[0].type == CitationType.GUARDRAIL
        assert result.citations[0].uuid_prefix == "def67890"
        assert result.mandate_count == 0
        assert result.guardrail_count == 1

    def test_parses_multiple_citations(self):
        """Test parsing multiple citations."""
        text = "According to [M:abc12345] and [G:def67890], and also [M:11223344]."
        result = parse_citations(text)

        assert len(result.citations) == 3
        assert result.mandate_count == 2
        assert result.guardrail_count == 1

    def test_handles_case_insensitive_type(self):
        """Test that citation type is case insensitive."""
        text = "[m:abc12345] and [M:def67890] and [g:11223344]"
        result = parse_citations(text)

        assert len(result.citations) == 3
        assert all(
            c.type in (CitationType.MANDATE, CitationType.GUARDRAIL) for c in result.citations
        )

    def test_lowercase_uuid_prefix(self):
        """Test that UUID prefixes are lowercased."""
        text = "[M:ABC12345]"
        result = parse_citations(text)

        assert result.citations[0].uuid_prefix == "abc12345"

    def test_returns_unique_uuids(self):
        """Test that unique_uuids contains deduplicated prefixes."""
        text = "[M:abc12345] and again [M:abc12345] and [G:abc12345]"
        result = parse_citations(text)

        assert len(result.citations) == 3
        assert len(result.unique_uuids) == 1
        assert "abc12345" in result.unique_uuids

    def test_empty_text_returns_empty_result(self):
        """Test empty text returns empty result."""
        result = parse_citations("")
        assert len(result.citations) == 0
        assert len(result.unique_uuids) == 0

    def test_no_citations_returns_empty_result(self):
        """Test text without citations returns empty result."""
        text = "This is just normal text without any citations."
        result = parse_citations(text)

        assert len(result.citations) == 0
        assert result.mandate_count == 0
        assert result.guardrail_count == 0

    def test_parses_reference_citation(self):
        """Test parsing a reference citation."""
        text = "Applied: [R:abc12345]."
        result = parse_citations(text)

        assert len(result.citations) == 1
        assert result.citations[0].type == CitationType.REFERENCE
        assert result.citations[0].uuid_prefix == "abc12345"
        assert result.mandate_count == 0
        assert result.guardrail_count == 0
        assert result.reference_count == 1

    def test_parses_mixed_mgr_citations(self):
        """Test parsing all three citation types together."""
        text = "[M:11111111] and [G:22222222] and [R:33333333]"
        result = parse_citations(text)

        assert len(result.citations) == 3
        assert result.mandate_count == 1
        assert result.guardrail_count == 1
        assert result.reference_count == 1
        assert len(result.unique_uuids) == 3

    def test_ignores_malformed_citations(self):
        """Test malformed citations are ignored."""
        # Invalid: not 8 hex chars
        text = "[M:abc123] [G:toolong12345] [X:abc12345]"
        result = parse_citations(text)

        assert len(result.citations) == 0

    def test_requires_8_hex_characters(self):
        """Test that exactly 8 hex characters are required."""
        text = "[M:1234567] [M:12345678] [M:123456789]"
        result = parse_citations(text)

        assert len(result.citations) == 1
        assert result.citations[0].uuid_prefix == "12345678"

    def test_hex_characters_only(self):
        """Test only hex characters are valid."""
        text = "[M:abcdefgh] [M:abcd1234]"
        result = parse_citations(text)

        # abcdefgh has 'g' and 'h' which are not hex
        assert len(result.citations) == 1
        assert result.citations[0].uuid_prefix == "abcd1234"


class TestExtractUuidPrefixes:
    """Tests for extract_uuid_prefixes function."""

    def test_extracts_prefixes(self):
        """Test extracting UUID prefixes."""
        text = "[M:abc12345] and [G:def67890]"
        prefixes = extract_uuid_prefixes(text)

        assert len(prefixes) == 2
        assert "abc12345" in prefixes
        assert "def67890" in prefixes

    def test_returns_unique_prefixes(self):
        """Test returns unique prefixes only."""
        text = "[M:abc12345] [M:abc12345] [G:abc12345]"
        prefixes = extract_uuid_prefixes(text)

        assert len(prefixes) == 1
        assert prefixes[0] == "abc12345"


class TestFormatCitation:
    """Tests for citation formatting functions."""

    def test_format_citation_mandate(self):
        """Test formatting a mandate citation."""
        uuid = "abc12345-6789-0abc-def0-123456789abc"
        result = format_citation(uuid, CitationType.MANDATE)

        assert result == "[M:abc12345]"

    def test_format_citation_guardrail(self):
        """Test formatting a guardrail citation."""
        uuid = "def67890-1234-5678-90ab-cdef12345678"
        result = format_citation(uuid, CitationType.GUARDRAIL)

        assert result == "[G:def67890]"

    def test_format_mandate_citation(self):
        """Test format_mandate_citation helper."""
        uuid = "abc12345-6789-0abc-def0-123456789abc"
        result = format_mandate_citation(uuid)

        assert result == "[M:abc12345]"

    def test_format_guardrail_citation(self):
        """Test format_guardrail_citation helper."""
        uuid = "def67890-1234-5678-90ab-cdef12345678"
        result = format_guardrail_citation(uuid)

        assert result == "[G:def67890]"

    def test_format_reference_citation(self):
        """Test format_reference_citation helper."""
        uuid = "abc12345-6789-0abc-def0-123456789abc"
        result = format_reference_citation(uuid)

        assert result == "[R:abc12345]"

    def test_format_uses_lowercase(self):
        """Test that formatting produces lowercase prefix."""
        uuid = "ABCDEF12-3456-7890-ABCD-EF1234567890"
        result = format_mandate_citation(uuid)

        assert result == "[M:abcdef12]"


class TestParseResultModel:
    """Tests for ParseResult model."""

    def test_default_values(self):
        """Test ParseResult default values."""
        result = ParseResult(citations=[])

        assert result.mandate_count == 0
        assert result.guardrail_count == 0
        assert result.reference_count == 0
        assert result.unique_uuids == []


class TestCitationModel:
    """Tests for Citation model."""

    def test_citation_creation(self):
        """Test creating a Citation."""
        citation = Citation(type=CitationType.MANDATE, uuid_prefix="abc12345")

        assert citation.type == CitationType.MANDATE
        assert citation.uuid_prefix == "abc12345"


class TestRealWorldExamples:
    """Tests with realistic LLM response text."""

    def test_parses_natural_response(self):
        """Test parsing a natural LLM response."""
        text = """Based on the guidelines [M:abc12345], I recommend using async patterns.

However, be careful not to violate the anti-pattern described in [G:def67890], which warns
against blocking calls in async code.

Additionally, per [M:11223344], always handle errors explicitly."""

        result = parse_citations(text)

        assert result.mandate_count == 2
        assert result.guardrail_count == 1
        assert len(result.unique_uuids) == 3

    def test_parses_response_with_no_citations(self):
        """Test parsing response without any citations (LLM ignored instructions)."""
        text = """I recommend using async patterns for better performance.
Make sure to handle errors and avoid blocking calls."""

        result = parse_citations(text)

        assert len(result.citations) == 0

    def test_parses_response_with_all_types(self):
        """Test parsing a response with mandates, guardrails, and references."""
        text = """Applied: [M:abc12345] for type safety. Applied: [G:def67890] for testing.
Also used [R:11223344] for the CLI reference guide."""

        result = parse_citations(text)

        assert result.mandate_count == 1
        assert result.guardrail_count == 1
        assert result.reference_count == 1
        assert len(result.unique_uuids) == 3

    def test_handles_citations_at_boundaries(self):
        """Test citations at start, end, and in middle."""
        text = "[M:11111111] at start, middle [G:22222222], and [M:33333333]"

        result = parse_citations(text)

        assert len(result.citations) == 3


@pytest.mark.unit
class TestParseFeedbackTags:
    """Tests for parse_feedback_tags function — new [[F:...]] format."""

    def test_parse_new_format_basic(self):
        """Test parsing a single feedback tag in new double-bracket format."""
        text = "[[F:friction:sf.cli:error message unhelpful when flag is invalid]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "friction"
        assert result.tags[0].component_id == "sf.cli"
        assert result.tags[0].description == "error message unhelpful when flag is invalid"
        assert result.friction_count == 1
        assert result.praise_count == 0

    def test_parse_new_format_multiple(self):
        """Test parsing multiple new-format tags of different types."""
        text = (
            "[[F:friction:sf.cli:bad error message]]"
            "[[F:praise:ah.memory:citation tracking worked seamlessly]]"
            "[[F:idea:sf.dt:cache ruff results for unchanged files]]"
            "[[F:improvement:xc.testing:test runner could parallelize by default]]"
        )
        result = parse_feedback_tags(text)

        assert len(result.tags) == 4
        assert result.friction_count == 1
        assert result.praise_count == 1
        assert result.idea_count == 1
        assert result.improvement_count == 1

    def test_parse_new_format_with_citations(self):
        """Test mixed [M:...] and [[F:...]] tags — only feedback parsed."""
        text = "Applied: [M:abc12345]. [[F:praise:sf.dt:dev-tools wrapper simplifies quality checks]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "praise"
        assert result.tags[0].component_id == "sf.dt"

    def test_parse_new_format_empty_description(self):
        """Test tag with empty description."""
        text = "[[F:friction:sf.cli:]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].description == ""

    def test_parse_new_format_invalid_component(self):
        """Test that invalid component format is ignored."""
        text = "[[F:friction:123bad:should be ignored]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 0

    def test_parse_new_format_case_insensitive_type(self):
        """Test that feedback type is case insensitive."""
        text = "[[F:FRICTION:sf.cli:all caps type]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "friction"

    def test_parse_new_format_invalid_type(self):
        """Test that unknown feedback types are ignored."""
        text = "[[F:bug:sf.cli:unknown type]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 0

    def test_parse_new_format_multiline_response(self):
        """Test parsing new-format tags from a realistic multi-line response."""
        text = """I've completed the implementation. A few observations:

[[F:friction:sf.dt:ruff --check passed invalid flag causing confusion]]
[[F:praise:ah.memory:citation system worked seamlessly this session]]

The changes are ready for review."""
        result = parse_feedback_tags(text)

        assert len(result.tags) == 2
        assert result.friction_count == 1
        assert result.praise_count == 1

    def test_parse_new_format_description_with_single_bracket(self):
        """Test description containing a single ] doesn't break parsing."""
        text = "[[F:friction:sf.cli:array[0] caused an error]]"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].description == "array[0] caused an error"

    def test_extract_feedback_tags_empty(self):
        """Test no tags returns empty list."""
        result = extract_feedback_tags("Just normal text without any tags")
        assert result == []

    def test_parse_feedback_tags_empty_text(self):
        """Test empty text returns empty result."""
        result = parse_feedback_tags("")
        assert len(result.tags) == 0


@pytest.mark.unit
class TestParseFeedbackTagsLegacy:
    """Tests for legacy [F:...] format backward compatibility."""

    def test_legacy_format_basic(self):
        """Test legacy single-bracket format still works as fallback."""
        text = "[F:friction:sf.cli] error message unhelpful when flag is invalid"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "friction"
        assert result.tags[0].component_id == "sf.cli"
        assert result.tags[0].description == "error message unhelpful when flag is invalid"

    def test_legacy_format_multiple(self):
        """Test multiple legacy tags."""
        text = (
            "[F:friction:sf.cli] bad error message\n"
            "[F:praise:ah.memory] citation tracking worked seamlessly\n"
        )
        result = parse_feedback_tags(text)

        assert len(result.tags) == 2
        assert result.friction_count == 1
        assert result.praise_count == 1

    def test_legacy_format_no_description(self):
        """Test legacy tag without trailing text gets empty description."""
        text = "[F:friction:sf.cli]\n"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].description == ""

    def test_new_format_takes_priority(self):
        """Test that new format is used when present, legacy ignored."""
        text = (
            "[[F:friction:sf.cli:new format feedback]]\n"
            "[F:praise:ah.memory] legacy format feedback\n"
        )
        result = parse_feedback_tags(text)

        # New format found, so legacy is not tried
        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "friction"
        assert result.tags[0].description == "new format feedback"

    def test_legacy_case_insensitive(self):
        """Test legacy format is case insensitive."""
        text = "[F:FRICTION:sf.cli] all caps type"
        result = parse_feedback_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].feedback_type == "friction"


@pytest.mark.unit
class TestParseSummaryTags:
    """Tests for parse_summary_tags function."""

    def test_parse_completed_summary(self):
        """Test parsing a completed summary tag."""
        text = "[[S:completed:Implemented inline summary parsing for session continuity]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].outcome == "completed"
        assert result.tags[0].description == "Implemented inline summary parsing for session continuity"

    def test_parse_partial_summary(self):
        """Test parsing a partial summary tag."""
        text = "[[S:partial:Started auth refactor, blocked by missing OAuth config]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].outcome == "partial"

    def test_parse_failed_summary(self):
        """Test parsing a failed summary tag."""
        text = "[[S:failed:Could not fix bug - root cause in external dependency]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].outcome == "failed"

    def test_parse_multiple_summary_tags(self):
        """Test parsing multiple summary tags (last wins at consumer)."""
        text = (
            "[[S:partial:Started working on the feature]]\n"
            "Some work in between...\n"
            "[[S:completed:Finished implementing the feature]]"
        )
        result = parse_summary_tags(text)

        assert len(result.tags) == 2
        assert result.tags[0].outcome == "partial"
        assert result.tags[1].outcome == "completed"

    def test_parse_summary_case_insensitive(self):
        """Test that outcome is case insensitive."""
        text = "[[S:COMPLETED:All caps outcome]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].outcome == "completed"

    def test_parse_summary_invalid_outcome_ignored(self):
        """Test that invalid outcomes are ignored."""
        text = "[[S:success:Not a valid outcome]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 0

    def test_parse_summary_mixed_with_citations_and_feedback(self):
        """Test summary tags don't interfere with citation and feedback parsing."""
        text = (
            "Applied: [M:abc12345]. "
            "[[F:praise:ah.memory:great system]] "
            "[[S:completed:Fixed the bug and added tests]]"
        )
        summary_result = parse_summary_tags(text)
        feedback_result = parse_feedback_tags(text)
        citation_result = parse_citations(text)

        assert len(summary_result.tags) == 1
        assert len(feedback_result.tags) == 1
        assert len(citation_result.citations) == 1

    def test_parse_summary_empty_input(self):
        """Test empty input returns empty result."""
        result = parse_summary_tags("")
        assert len(result.tags) == 0

    def test_parse_summary_no_tags(self):
        """Test text without summary tags returns empty result."""
        result = parse_summary_tags("Just normal text without any tags.")
        assert len(result.tags) == 0

    def test_parse_summary_description_with_single_bracket(self):
        """Test description containing single ] doesn't break parsing."""
        text = "[[S:completed:Fixed array[0] indexing bug]]"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].description == "Fixed array[0] indexing bug"

    def test_extract_summary_tags_convenience(self):
        """Test extract_summary_tags convenience function."""
        text = "[[S:completed:Done]]"
        tags = extract_summary_tags(text)

        assert len(tags) == 1
        assert tags[0].outcome == "completed"
        assert tags[0].description == "Done"

    def test_parse_summary_repairs_terminal_curly_brace_near_miss(self):
        """A aterm `]}` near-miss should be normalized for parsing."""
        text = "[[S:completed:Reported the current git branch name]}"
        result = parse_summary_tags(text)

        assert len(result.tags) == 1
        assert result.tags[0].outcome == "completed"
        assert result.tags[0].description == "Reported the current git branch name"
