"""Tests for citation parser module."""

from app.services.memory.citation_parser import (
    Citation,
    CitationType,
    ParseResult,
    extract_uuid_prefixes,
    format_citation,
    format_guardrail_citation,
    format_mandate_citation,
    parse_citations,
)


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

    def test_handles_citations_at_boundaries(self):
        """Test citations at start, end, and in middle."""
        text = "[M:11111111] at start, middle [G:22222222], and [M:33333333]"

        result = parse_citations(text)

        assert len(result.citations) == 3
