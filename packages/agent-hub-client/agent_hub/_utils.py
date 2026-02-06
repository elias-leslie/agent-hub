"""Internal utilities for Agent Hub client."""

import inspect
from pathlib import Path

import httpx

from agent_hub.exceptions import (
    AgentHubError,
    AuthenticationError,
    ClientDisabledError,
    RateLimitError,
    ServerError,
    ValidationError,
)


def get_caller_path(skip_frames: int = 2) -> str | None:
    """Get the file path of the caller using inspect.

    Args:
        skip_frames: Number of frames to skip (to get past library internals).

    Returns:
        Relative path from cwd to caller file, or absolute path if outside cwd.
    """
    try:
        stack = inspect.stack()
        # Skip frames: _get_caller_path, _get_client, caller's method
        if len(stack) > skip_frames:
            frame = stack[skip_frames]
            caller_file = Path(frame.filename)
            try:
                # Try to make it relative to cwd for cleaner logs
                return str(caller_file.relative_to(Path.cwd()))
            except ValueError:
                # Outside cwd, use absolute path
                return str(caller_file)
    except Exception:
        pass
    return None


def handle_error(response: httpx.Response) -> None:
    """Raise appropriate exception for error responses."""
    status = response.status_code
    try:
        data = response.json()
        detail = data.get("detail", response.text)
    except Exception:
        detail = response.text
        data = {}

    if status == 401:
        raise AuthenticationError(f"Authentication failed: {detail}", status_code=401)
    elif status == 403:
        # Check for kill switch (client disabled) response
        error_type = data.get("error") if isinstance(data, dict) else None
        if error_type in (
            "client_disabled",
            "client_purpose_disabled",
            "purpose_disabled",
        ):
            retry_after = data.get("retry_after", -1) if isinstance(data, dict) else -1
            if retry_after == -1:
                raise ClientDisabledError(
                    message=data.get("message", "Client disabled")
                    if isinstance(data, dict)
                    else "Client disabled",
                    blocked_entity=data.get("blocked_entity")
                    if isinstance(data, dict)
                    else None,
                    reason=data.get("reason") if isinstance(data, dict) else None,
                    disabled_at=data.get("disabled_at")
                    if isinstance(data, dict)
                    else None,
                )
        raise AgentHubError(f"Forbidden: {detail}", status_code=403)
    elif status == 429:
        retry_after = response.headers.get("Retry-After")
        raise RateLimitError(
            f"Rate limit exceeded: {detail}",
            retry_after=float(retry_after) if retry_after else None,
        )
    elif status == 422:
        raise ValidationError(f"Validation error: {detail}", status_code=422)
    elif status >= 500:
        raise ServerError(f"Server error: {detail}", status_code=status)
    else:
        raise AgentHubError(f"Request failed: {detail}", status_code=status)
