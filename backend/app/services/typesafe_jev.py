"""Shared TypeSafe System One transport and typed response validation."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import httpx

from app.api.typesafe_jev_schemas import (
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    ScoreAnswer,
    ScoreQuestion,
    SystemOneRequest,
    TypeSafeProviderResponse,
)
from app.services.credential_manager import get_credential_manager

TYPESAFE_PROVIDER_ID = "typesafe"
TYPESAFE_API_URL = "https://api.typesafe.ai/v1/systemone"
TYPESAFE_KEY_FILE = Path("/home/kasadis/.config/typesafe/credentials.env")
TYPESAFE_KEY_NAME = "TYPESAFE_API_KEY"

JEV_MAX_INPUT_TOKENS = 64_000


class TypeSafeJevError(RuntimeError):
    """A fail-visible client, contract, or provider error."""

    def __init__(
        self,
        kind: str,
        detail: str,
        *,
        status_code: int = 409,
        provider_request_id: str | None = None,
        provider_response: TypeSafeProviderResponse | None = None,
    ) -> None:
        super().__init__(detail)
        self.kind = kind
        self.detail = detail
        self.status_code = status_code
        self.provider_request_id = provider_request_id
        self.provider_response = provider_response


def _request_payload(request: SystemOneRequest) -> dict[str, Any]:
    return {
        "state": request.state,
        "model": request.model,
        "questions": {
            key: question.model_dump(mode="json", exclude_none=True)
            for key, question in request.questions.items()
        },
    }


def _load_key_file(path: Path = TYPESAFE_KEY_FILE) -> str:
    """Read one exact owner-only assignment without executing shell syntax."""
    try:
        metadata = path.stat()
    except OSError as exc:
        raise TypeSafeJevError("credential_unavailable", "TypeSafe credential file is unavailable") from exc
    if metadata.st_uid != os.geteuid() or stat.S_IMODE(metadata.st_mode) & 0o077:
        raise TypeSafeJevError(
            "credential_permissions",
            "TypeSafe credential file must be owned by the service user and mode 0600",
        )

    values: list[str] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                name, separator, value = line.partition("=")
                if separator and name.strip() == TYPESAFE_KEY_NAME:
                    values.append(value.strip())
    except OSError as exc:
        raise TypeSafeJevError("credential_unavailable", "TypeSafe credential file is unreadable") from exc

    if len(values) != 1 or not values[0]:
        raise TypeSafeJevError(
            "credential_invalid",
            f"credential file must contain exactly one non-empty {TYPESAFE_KEY_NAME} assignment",
        )
    return values[0]


def resolve_typesafe_api_key() -> str:
    """Prefer Agent Hub's encrypted broker, then its owner-only credential file."""
    manager = get_credential_manager()
    if manager.is_initialized:
        key = manager.get_api_key(TYPESAFE_PROVIDER_ID)
        if key:
            return key
    return _load_key_file()


def _validate_provider_response(
    request: SystemOneRequest,
    response: TypeSafeProviderResponse,
    max_input_tokens: int = JEV_MAX_INPUT_TOKENS,
) -> None:
    if response.model != request.model:
        raise TypeSafeJevError(
            "model_version_changed",
            f"expected {request.model}, provider reported {response.model}",
            status_code=502,
        )
    if response.usage.input_tokens > max_input_tokens:
        raise TypeSafeJevError(
            "provider_contract_changed",
            "provider reported input usage above the configured model context window",
            status_code=502,
        )
    if response.answers.keys() != request.questions.keys():
        raise TypeSafeJevError(
            "unsupported_output",
            "provider answer ids did not exactly match the requested question ids",
            status_code=502,
        )

    for question_id, question in request.questions.items():
        answer = response.answers[question_id]
        if isinstance(question, NoulQuestion):
            if not isinstance(answer, NoulAnswer):
                raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
            continue
        if isinstance(question, ChoiceQuestion):
            if not isinstance(answer, ChoiceAnswer):
                raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
            expected = set(question.criteria)
            if answer.choice not in expected or set(answer.probabilities) != expected:
                raise TypeSafeJevError(
                    "unsupported_output",
                    f"{question_id} choice output did not preserve the requested rubric",
                    status_code=502,
                )
            if any(probability < 0 or probability > 1 for probability in answer.probabilities.values()):
                raise TypeSafeJevError("unsupported_output", f"{question_id} probabilities were invalid", status_code=502)
            continue
        if not isinstance(question, ScoreQuestion) or not isinstance(answer, ScoreAnswer):
            raise TypeSafeJevError("unsupported_output", f"{question_id} answer type changed", status_code=502)
        expected_levels = {str(index) for index in range(len(question.criteria))}
        if set(answer.legend) != expected_levels or set(answer.probabilities) != expected_levels:
            raise TypeSafeJevError(
                "unsupported_output",
                f"{question_id} score output did not preserve the requested rubric",
                status_code=502,
            )
        if not 0 <= answer.score <= len(question.criteria) - 1:
            raise TypeSafeJevError("unsupported_output", f"{question_id} score was out of range", status_code=502)
        if any(probability < 0 or probability > 1 for probability in answer.probabilities.values()):
            raise TypeSafeJevError("unsupported_output", f"{question_id} probabilities were invalid", status_code=502)


async def call_typesafe_jev(
    request: SystemOneRequest,
    *,
    api_key: str,
    http_client: httpx.AsyncClient | None = None,
    max_input_tokens: int = JEV_MAX_INPUT_TOKENS,
) -> tuple[TypeSafeProviderResponse, str | None]:
    """Call the official HTTP endpoint once and return a fully validated response."""
    owns_client = http_client is None
    client = http_client or httpx.AsyncClient(timeout=None, trust_env=False, follow_redirects=False)
    try:
        response = await client.post(
            TYPESAFE_API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=_request_payload(request),
        )
        provider_request_id = response.headers.get("x-typesafe-request-id")
        if not response.is_success:
            raise TypeSafeJevError(
                "provider_http_error",
                f"TypeSafe returned HTTP {response.status_code}; billing is uncertain",
                status_code=502,
                provider_request_id=provider_request_id,
            )
        try:
            provider_response = TypeSafeProviderResponse.model_validate(response.json())
        except (ValueError, TypeError) as exc:
            raise TypeSafeJevError(
                "unsupported_output",
                "TypeSafe returned an unsupported response; billing is uncertain",
                status_code=502,
            ) from exc
        try:
            _validate_provider_response(request, provider_response, max_input_tokens)
        except TypeSafeJevError as exc:
            exc.provider_request_id = provider_request_id
            exc.provider_response = provider_response
            raise
        return provider_response, provider_request_id
    finally:
        if owns_client:
            await client.aclose()


__all__ = [
    "JEV_MAX_INPUT_TOKENS",
    "TypeSafeJevError",
    "call_typesafe_jev",
    "resolve_typesafe_api_key",
]
