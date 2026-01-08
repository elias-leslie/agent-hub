"""Tests for maker-checker verification pattern."""

from unittest.mock import AsyncMock, patch

import pytest

from app.services.orchestration.maker_checker import (
    CodeReviewPattern,
    MakerChecker,
    VerificationResult,
)
from app.services.orchestration.subagent import SubagentConfig, SubagentResult


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_approved_result(self):
        """Test approved verification result."""
        maker_result = SubagentResult(
            subagent_id="maker",
            name="maker",
            content="Generated code",
            status="completed",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=200,
        )
        checker_result = SubagentResult(
            subagent_id="checker",
            name="checker",
            content="DECISION: APPROVED\nCONFIDENCE: 0.95",
            status="completed",
            provider="gemini",
            model="gemini-2.0-flash",
            input_tokens=200,
            output_tokens=50,
        )

        result = VerificationResult(
            maker_result=maker_result,
            checker_result=checker_result,
            approved=True,
            issues=[],
            suggestions=[],
            confidence=0.95,
            final_output="Generated code",
            iterations=1,
        )

        assert result.approved is True
        assert result.confidence == 0.95
        assert len(result.issues) == 0

    def test_rejected_result(self):
        """Test rejected verification result."""
        maker_result = SubagentResult(
            subagent_id="maker",
            name="maker",
            content="Bad code",
            status="completed",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=200,
        )
        checker_result = SubagentResult(
            subagent_id="checker",
            name="checker",
            content="DECISION: NEEDS_REVISION\nISSUES:\n- Bug in line 5",
            status="completed",
            provider="gemini",
            model="gemini-2.0-flash",
            input_tokens=200,
            output_tokens=100,
        )

        result = VerificationResult(
            maker_result=maker_result,
            checker_result=checker_result,
            approved=False,
            issues=["Bug in line 5"],
            suggestions=["Fix the loop"],
            confidence=0.7,
            final_output="Bad code",
            iterations=3,
        )

        assert result.approved is False
        assert len(result.issues) == 1
        assert result.iterations == 3


class TestMakerChecker:
    """Tests for MakerChecker."""

    def test_initialization(self):
        """Test maker-checker initialization."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")

        verifier = MakerChecker(
            maker_config=maker_config,
            checker_config=checker_config,
            max_iterations=3,
        )

        assert verifier._max_iterations == 3

    def test_default_checker_prompt(self):
        """Test default checker prompt is applied."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")

        verifier = MakerChecker(
            maker_config=maker_config,
            checker_config=checker_config,
        )

        # Checker should have a system prompt
        assert verifier._checker_config.system_prompt is not None
        assert "verification" in verifier._checker_config.system_prompt.lower()

    def test_parse_checker_response_approved(self):
        """Test parsing approved checker response."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config)

        response = """DECISION: APPROVED
CONFIDENCE: 0.95
ISSUES:
SUGGESTIONS:
- Consider adding docstrings"""

        parsed = verifier._parse_checker_response(response)

        assert parsed["approved"] is True
        assert parsed["confidence"] == 0.95
        assert len(parsed["issues"]) == 0
        assert len(parsed["suggestions"]) == 1

    def test_parse_checker_response_rejected(self):
        """Test parsing rejected checker response."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config)

        response = """DECISION: NEEDS_REVISION
CONFIDENCE: 0.6
ISSUES:
- Missing error handling
- SQL injection vulnerability
SUGGESTIONS:
- Add try/except blocks
- Use parameterized queries"""

        parsed = verifier._parse_checker_response(response)

        assert parsed["approved"] is False
        assert parsed["confidence"] == 0.6
        assert len(parsed["issues"]) == 2
        assert len(parsed["suggestions"]) == 2

    def test_parse_checker_response_invalid(self):
        """Test parsing invalid checker response."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config)

        response = "This is not a valid response format"

        parsed = verifier._parse_checker_response(response)

        # Should return defaults
        assert parsed["approved"] is False
        assert parsed["confidence"] == 0.5

    @pytest.mark.asyncio
    async def test_verify_approved_first_try(self):
        """Test verification approved on first try."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config, max_iterations=3)

        maker_result = SubagentResult(
            subagent_id="maker",
            name="maker",
            content="Perfect code",
            status="completed",
            provider="claude",
            model="claude-sonnet-4-5",
            input_tokens=100,
            output_tokens=200,
        )
        checker_result = SubagentResult(
            subagent_id="checker",
            name="checker",
            content="DECISION: APPROVED\nCONFIDENCE: 0.95",
            status="completed",
            provider="gemini",
            model="gemini-2.0-flash",
            input_tokens=200,
            output_tokens=50,
        )

        call_count = 0

        async def mock_spawn(self, task, config, **kwargs):
            nonlocal call_count
            call_count += 1
            if config.name == "maker":
                return maker_result
            return checker_result

        with patch.object(
            verifier._subagent_manager, "spawn", mock_spawn
        ):
            result = await verifier.verify(task="Write some code")

            assert result.approved is True
            assert result.iterations == 1
            assert call_count == 2  # One maker, one checker

    @pytest.mark.asyncio
    async def test_verify_needs_multiple_iterations(self):
        """Test verification requiring multiple iterations."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config, max_iterations=3)

        iteration = 0

        async def mock_spawn(self, task, config, **kwargs):
            nonlocal iteration
            if config.name == "maker":
                iteration += 1
                return SubagentResult(
                    subagent_id="maker",
                    name="maker",
                    content=f"Code v{iteration}",
                    status="completed",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=100,
                    output_tokens=200,
                )
            else:
                # Approve on third iteration
                if iteration >= 3:
                    return SubagentResult(
                        subagent_id="checker",
                        name="checker",
                        content="DECISION: APPROVED\nCONFIDENCE: 0.9",
                        status="completed",
                        provider="gemini",
                        model="gemini-2.0-flash",
                        input_tokens=200,
                        output_tokens=50,
                    )
                return SubagentResult(
                    subagent_id="checker",
                    name="checker",
                    content="DECISION: NEEDS_REVISION\nCONFIDENCE: 0.5\nISSUES:\n- Needs work",
                    status="completed",
                    provider="gemini",
                    model="gemini-2.0-flash",
                    input_tokens=200,
                    output_tokens=100,
                )

        with patch.object(
            verifier._subagent_manager, "spawn", mock_spawn
        ):
            result = await verifier.verify(task="Write some code")

            assert result.approved is True
            assert result.iterations == 3

    @pytest.mark.asyncio
    async def test_verify_max_iterations_reached(self):
        """Test verification hitting max iterations."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config, max_iterations=2)

        async def mock_spawn(self, task, config, **kwargs):
            if config.name == "maker":
                return SubagentResult(
                    subagent_id="maker",
                    name="maker",
                    content="Still bad code",
                    status="completed",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=100,
                    output_tokens=200,
                )
            return SubagentResult(
                subagent_id="checker",
                name="checker",
                content="DECISION: NEEDS_REVISION\nCONFIDENCE: 0.3\nISSUES:\n- Still broken",
                status="completed",
                provider="gemini",
                model="gemini-2.0-flash",
                input_tokens=200,
                output_tokens=100,
            )

        with patch.object(
            verifier._subagent_manager, "spawn", mock_spawn
        ):
            result = await verifier.verify(task="Write some code")

            assert result.approved is False
            assert result.iterations == 2

    @pytest.mark.asyncio
    async def test_verify_maker_fails(self):
        """Test verification when maker fails."""
        maker_config = SubagentConfig(name="maker")
        checker_config = SubagentConfig(name="checker")
        verifier = MakerChecker(maker_config, checker_config)

        async def mock_spawn(task, config, **kwargs):
            if config.name == "maker":
                return SubagentResult(
                    subagent_id="maker",
                    name="maker",
                    content="",
                    status="error",
                    provider="claude",
                    model="claude-sonnet-4-5",
                    input_tokens=0,
                    output_tokens=0,
                    error="API error",
                )
            return SubagentResult(
                subagent_id="checker",
                name="checker",
                content="Should not be called",
                status="completed",
                provider="gemini",
                model="gemini-2.0-flash",
                input_tokens=0,
                output_tokens=0,
            )

        with patch(
            "app.services.orchestration.subagent.SubagentManager.spawn",
            new=mock_spawn,
        ):
            # Should raise because maker failed to produce output
            with pytest.raises(RuntimeError, match="Maker failed"):
                await verifier.verify(task="Write some code")


class TestCodeReviewPattern:
    """Tests for specialized code review pattern."""

    def test_initialization(self):
        """Test code review pattern initialization."""
        reviewer = CodeReviewPattern()

        assert reviewer._maker_config.name == "code_generator"
        assert reviewer._checker_config.name == "code_reviewer"

    def test_custom_providers(self):
        """Test code review with custom providers."""
        reviewer = CodeReviewPattern(
            maker_provider="gemini",
            checker_provider="claude",
            max_iterations=2,
        )

        assert reviewer._maker_config.provider == "gemini"
        assert reviewer._checker_config.provider == "claude"
        assert reviewer._max_iterations == 2

    def test_system_prompts(self):
        """Test that system prompts are set correctly."""
        reviewer = CodeReviewPattern()

        assert "programmer" in reviewer._maker_config.system_prompt.lower()
        assert "reviewer" in reviewer._checker_config.system_prompt.lower()
