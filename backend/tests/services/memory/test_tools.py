"""Tests for memory tools module."""

from datetime import UTC, datetime

from app.services.memory.service import (
    MemoryCategory,
    MemoryScope,
    MemorySearchResult,
    MemorySource,
)
from app.services.memory.tools import (
    RecordDiscoveryRequest,
    RecordGotchaRequest,
    RecordPatternRequest,
    RecordResponse,
    SessionContextResponse,
    format_session_context_for_injection,
)


class TestRecordDiscoveryRequest:
    """Tests for RecordDiscoveryRequest model."""

    def test_required_fields(self):
        """Test required fields."""
        request = RecordDiscoveryRequest(
            file_path="src/main.py",
            description="Found a useful utility function",
        )
        assert request.file_path == "src/main.py"
        assert request.description == "Found a useful utility function"

    def test_default_values(self):
        """Test default values."""
        request = RecordDiscoveryRequest(
            file_path="test.py",
            description="Test",
        )
        assert request.category == MemoryCategory.REFERENCE
        assert request.scope == MemoryScope.PROJECT
        assert request.scope_id is None

    def test_custom_values(self):
        """Test custom category and scope."""
        request = RecordDiscoveryRequest(
            file_path="api/routes.py",
            description="API pattern",
            category=MemoryCategory.REFERENCE,
            scope=MemoryScope.GLOBAL,
        )
        assert request.category == MemoryCategory.REFERENCE
        assert request.scope == MemoryScope.GLOBAL


class TestRecordGotchaRequest:
    """Tests for RecordGotchaRequest model."""

    def test_required_fields(self):
        """Test required fields."""
        request = RecordGotchaRequest(
            gotcha="Async context manager issue",
            context="Using async with in sync function",
        )
        assert request.gotcha == "Async context manager issue"
        assert request.context == "Using async with in sync function"

    def test_optional_solution(self):
        """Test optional solution field."""
        request = RecordGotchaRequest(
            gotcha="Import error",
            context="Circular imports",
            solution="Use lazy imports",
        )
        assert request.solution == "Use lazy imports"

    def test_default_scope(self):
        """Test default scope is PROJECT."""
        request = RecordGotchaRequest(
            gotcha="Test",
            context="Test context",
        )
        assert request.scope == MemoryScope.PROJECT


class TestRecordPatternRequest:
    """Tests for RecordPatternRequest model."""

    def test_required_fields(self):
        """Test required fields."""
        request = RecordPatternRequest(
            pattern="Repository pattern",
            applies_to="Data access layer",
        )
        assert request.pattern == "Repository pattern"
        assert request.applies_to == "Data access layer"

    def test_optional_example(self):
        """Test optional example field."""
        request = RecordPatternRequest(
            pattern="Singleton",
            applies_to="Service initialization",
            example="class Service:\n    _instance = None",
        )
        assert "Singleton" in request.example or "instance" in request.example


class TestRecordResponse:
    """Tests for RecordResponse model."""

    def test_success_response(self):
        """Test successful response."""
        response = RecordResponse(
            success=True,
            episode_uuid="uuid-123",
            message="Discovery recorded",
        )
        assert response.success
        assert response.episode_uuid == "uuid-123"
        assert response.message == "Discovery recorded"

    def test_failure_response(self):
        """Test failure response."""
        response = RecordResponse(
            success=False,
            episode_uuid="",
            message="Failed to record",
        )
        assert not response.success
        assert response.episode_uuid == ""


class TestSessionContextResponse:
    """Tests for SessionContextResponse model."""

    def test_empty_response(self):
        """Test empty response defaults."""
        response = SessionContextResponse()
        assert response.discoveries == []
        assert response.gotchas == []
        assert response.patterns == []
        assert response.session_count == 0

    def test_with_items(self):
        """Test response with items."""
        now = datetime.now(UTC)
        response = SessionContextResponse(
            discoveries=[
                MemorySearchResult(
                    uuid="d1",
                    content="discovery",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                )
            ],
            gotchas=[
                MemorySearchResult(
                    uuid="g1",
                    content="gotcha",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                )
            ],
            session_count=2,
        )
        assert len(response.discoveries) == 1
        assert len(response.gotchas) == 1
        assert response.session_count == 2


class TestFormatSessionContextForInjection:
    """Tests for format_session_context_for_injection function."""

    def test_empty_context_returns_empty_string(self):
        """Test empty context returns empty string."""
        context = SessionContextResponse()
        result = format_session_context_for_injection(context)
        assert result == ""

    def test_zero_session_count_returns_empty(self):
        """Test zero session count returns empty string."""
        context = SessionContextResponse(session_count=0)
        result = format_session_context_for_injection(context)
        assert result == ""

    def test_patterns_section(self):
        """Test patterns are formatted correctly."""
        now = datetime.now(UTC)
        context = SessionContextResponse(
            patterns=[
                MemorySearchResult(
                    uuid="p1",
                    content="Always use async methods",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
                MemorySearchResult(
                    uuid="p2",
                    content="Use dependency injection",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),
            ],
            session_count=2,
        )
        result = format_session_context_for_injection(context)

        assert "## Relevant Patterns" in result
        assert "- Always use async methods" in result
        assert "- Use dependency injection" in result

    def test_gotchas_section(self):
        """Test gotchas are formatted correctly."""
        now = datetime.now(UTC)
        context = SessionContextResponse(
            gotchas=[
                MemorySearchResult(
                    uuid="g1",
                    content="Don't use sync calls in async context",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
            session_count=1,
        )
        result = format_session_context_for_injection(context)

        assert "## Known Gotchas" in result
        assert "- Don't use sync calls in async context" in result

    def test_discoveries_section(self):
        """Test discoveries are formatted correctly."""
        now = datetime.now(UTC)
        context = SessionContextResponse(
            discoveries=[
                MemorySearchResult(
                    uuid="d1",
                    content="Found auth module in src/auth/",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),
            ],
            session_count=1,
        )
        result = format_session_context_for_injection(context)

        assert "## Recent Discoveries" in result
        assert "- Found auth module in src/auth/" in result

    def test_all_sections_together(self):
        """Test all sections are included in correct order."""
        now = datetime.now(UTC)
        context = SessionContextResponse(
            patterns=[
                MemorySearchResult(
                    uuid="p1",
                    content="Pattern content",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
            gotchas=[
                MemorySearchResult(
                    uuid="g1",
                    content="Gotcha content",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
            discoveries=[
                MemorySearchResult(
                    uuid="d1",
                    content="Discovery content",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.8,
                    created_at=now,
                    facts=[],
                ),
            ],
            session_count=3,
        )
        result = format_session_context_for_injection(context)

        # Check all sections present
        assert "## Relevant Patterns" in result
        assert "## Known Gotchas" in result
        assert "## Recent Discoveries" in result

        # Check order (Patterns -> Gotchas -> Discoveries)
        patterns_pos = result.index("## Relevant Patterns")
        gotchas_pos = result.index("## Known Gotchas")
        discoveries_pos = result.index("## Recent Discoveries")
        assert patterns_pos < gotchas_pos < discoveries_pos

    def test_discoveries_limited_to_five(self):
        """Test discoveries are limited to 5 items."""
        now = datetime.now(UTC)
        many_discoveries = [
            MemorySearchResult(
                uuid=f"d{i}",
                content=f"Discovery {i}",
                source=MemorySource.SYSTEM,
                relevance_score=0.8,
                created_at=now,
                facts=[],
            )
            for i in range(10)
        ]
        context = SessionContextResponse(
            discoveries=many_discoveries,
            session_count=10,
        )
        result = format_session_context_for_injection(context)

        # Count discovery items (lines starting with "- Discovery")
        discovery_lines = [line for line in result.split("\n") if line.startswith("- Discovery")]
        assert len(discovery_lines) == 5

    def test_only_patterns_no_extra_sections(self):
        """Test only patterns section when others are empty."""
        now = datetime.now(UTC)
        context = SessionContextResponse(
            patterns=[
                MemorySearchResult(
                    uuid="p1",
                    content="Pattern only",
                    source=MemorySource.SYSTEM,
                    relevance_score=0.9,
                    created_at=now,
                    facts=[],
                ),
            ],
            session_count=1,
        )
        result = format_session_context_for_injection(context)

        assert "## Relevant Patterns" in result
        assert "## Known Gotchas" not in result
        assert "## Recent Discoveries" not in result
