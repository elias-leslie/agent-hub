"""Maker-checker verification endpoints."""

from fastapi import APIRouter

from app.api.orchestration_models import (
    CodeReviewRequest,
    MakerCheckerRequest,
    MakerCheckerResponse,
)
from app.services.orchestration import (
    CodeReviewPattern,
    MakerChecker,
    SubagentConfig,
)
from app.services.telemetry import get_current_trace_id

router = APIRouter()


@router.post("/maker-checker", response_model=MakerCheckerResponse)
async def run_maker_checker(request: MakerCheckerRequest) -> MakerCheckerResponse:
    """
    Run maker-checker verification.

    Uses one agent to generate output and another to verify.
    """
    trace_id = get_current_trace_id()

    maker_config = SubagentConfig(
        name="maker",
        provider=request.maker_provider,
    )
    checker_config = SubagentConfig(
        name="checker",
        provider=request.checker_provider,
    )

    verifier = MakerChecker(
        maker_config=maker_config,
        checker_config=checker_config,
        max_iterations=request.max_iterations,
    )

    result = await verifier.verify(
        task=request.task,
        trace_id=trace_id,
    )

    return MakerCheckerResponse(
        approved=result.approved,
        confidence=result.confidence,
        final_output=result.final_output,
        iterations=result.iterations,
        issues=result.issues,
        suggestions=result.suggestions,
        trace_id=trace_id,
    )


@router.post("/code-review", response_model=MakerCheckerResponse)
async def run_code_review(request: CodeReviewRequest) -> MakerCheckerResponse:
    """
    Run code generation with code review.

    Specialized maker-checker for code tasks.
    """
    trace_id = get_current_trace_id()

    reviewer = CodeReviewPattern(
        maker_provider=request.maker_provider,
        checker_provider=request.checker_provider,
    )

    result = await reviewer.verify(
        task=request.task,
        trace_id=trace_id,
    )

    return MakerCheckerResponse(
        approved=result.approved,
        confidence=result.confidence,
        final_output=result.final_output,
        iterations=result.iterations,
        issues=result.issues,
        suggestions=result.suggestions,
        trace_id=trace_id,
    )
