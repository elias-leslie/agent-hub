"""Agent Hub client exceptions."""


class AgentHubError(Exception):
    """Base exception for Agent Hub client errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ValidationError(AgentHubError):
    """Request validation failed."""

    pass


class AuthenticationError(AgentHubError):
    """Authentication failed (401)."""

    pass


class RateLimitError(AgentHubError):
    """Rate limit exceeded (429)."""

    def __init__(
        self, message: str, retry_after: float | None = None
    ) -> None:
        super().__init__(message, status_code=429)
        self.retry_after = retry_after


class ServerError(AgentHubError):
    """Server error (5xx)."""

    pass


class ClientDisabledError(AgentHubError):
    """Client has been disabled via kill switch (403 with retry_after=-1).

    When this error is raised, the client should enter dormant mode
    and not make further requests until re-enabled.
    """

    def __init__(
        self,
        message: str,
        blocked_entity: str | None = None,
        reason: str | None = None,
        disabled_at: str | None = None,
    ) -> None:
        super().__init__(message, status_code=403)
        self.blocked_entity = blocked_entity
        self.reason = reason
        self.disabled_at = disabled_at
