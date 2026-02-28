"""Provider exception class definitions."""


class ProviderError(Exception):
    """Base exception for provider errors."""

    def __init__(
        self,
        message: str,
        provider: str,
        retriable: bool = False,
        status_code: int | None = None,
    ):
        super().__init__(message)
        self.provider = provider
        self.retriable = retriable
        self.status_code = status_code


class RateLimitError(ProviderError):
    """Provider rate limit exceeded."""

    def __init__(
        self,
        provider: str,
        retry_after: float | None = None,
        quota_details: dict[str, str] | None = None,
    ):
        super().__init__(
            f"Rate limit exceeded for {provider}",
            provider=provider,
            retriable=True,
            status_code=429,
        )
        self.retry_after = retry_after
        self.quota_details = quota_details or {}


class AuthenticationError(ProviderError):
    """Provider authentication failed."""

    def __init__(self, provider: str):
        super().__init__(
            f"Authentication failed for {provider}",
            provider=provider,
            retriable=False,
            status_code=401,
        )


class CircuitBreakerError(ProviderError):
    """Circuit breaker opened due to repeated failures (thrashing)."""

    def __init__(
        self,
        provider: str,
        consecutive_failures: int,
        last_error_signature: str,
        cooldown_until: float | None = None,
    ):
        super().__init__(
            f"Circuit breaker open for {provider}: {consecutive_failures} consecutive failures",
            provider=provider,
            retriable=True,  # Retriable after cooldown
            status_code=503,
        )
        self.consecutive_failures = consecutive_failures
        self.last_error_signature = last_error_signature
        self.cooldown_until = cooldown_until
