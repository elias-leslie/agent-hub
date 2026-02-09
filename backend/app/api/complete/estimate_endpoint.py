"""Token estimation endpoint."""

from __future__ import annotations

from typing import cast

from app.api.complete.schemas import EstimateRequest, EstimateResponse
from app.services.token_counter import estimate_request


async def handle_estimate(request: EstimateRequest) -> EstimateResponse:
    """Estimate tokens and cost before making a completion request.

    Args:
        request: The estimation request

    Returns:
        Token and cost estimation response
    """
    from app.constants import resolve_model

    resolved_model = resolve_model(request.model)
    messages_dict = [{"role": m.role, "content": m.content} for m in request.messages]
    estimate_result = estimate_request(
        messages=cast(list[dict[str, str]], messages_dict),
        model=resolved_model,
    )
    return EstimateResponse(
        input_tokens=estimate_result.input_tokens,
        estimated_output_tokens=estimate_result.estimated_output_tokens,
        total_tokens=estimate_result.total_tokens,
        estimated_cost_usd=estimate_result.estimated_cost_usd,
        context_limit=estimate_result.context_limit,
        context_usage_percent=estimate_result.context_usage_percent,
        context_warning=estimate_result.context_warning,
    )
