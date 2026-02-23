"""Per-client rate limiting backed by Redis counters.

Enforces requests-per-minute (RPM) and tokens-per-minute (TPM) limits
stored on the Client model. Uses minute-based sliding windows with
auto-expiring Redis keys.

Fail-OPEN on Redis errors: rate limiting is a soft gate, not security.
"""

import logging
from datetime import UTC, datetime

import redis.asyncio as aioredis

from app.config import settings

logger = logging.getLogger(__name__)

# Redis key patterns
_RPM_KEY = "rate_limit:rpm:{client_id}:{minute}"  # requests per minute counter
_TPM_KEY = "rate_limit:tpm:{client_id}:{minute}"  # tokens per minute counter

# TTL (seconds) — slightly longer than the 60-second window to handle edge cases
_MINUTE_TTL = 90

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    """Get or create async Redis client for rate limiting."""
    global _redis
    if _redis is None:
        _redis = aioredis.from_url(settings.agent_hub_redis_url, decode_responses=True)
    return _redis


async def check_client_rate_limit(
    client_id: str, rpm_limit: int | None, tpm_limit: int | None
) -> tuple[bool, str | None]:
    """Check and enforce per-client rate limits.

    Increments the RPM counter on check (pre-request). Does NOT increment
    the TPM counter — that happens post-request via record_client_tokens().

    Args:
        client_id: The client identifier.
        rpm_limit: Maximum requests per minute, or None/0 for unlimited.
        tpm_limit: Maximum tokens per minute, or None/0 for unlimited.

    Returns:
        (True, None) if the request is allowed.
        (False, reason) if the request is rate-limited.
    """
    try:
        r = _get_redis()
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")

        # --- RPM check (increment-then-check) ---
        if rpm_limit and rpm_limit > 0:
            rpm_key = _RPM_KEY.format(client_id=client_id, minute=minute)
            current_rpm = await r.incr(rpm_key)
            if current_rpm == 1:
                await r.expire(rpm_key, _MINUTE_TTL)

            if current_rpm > rpm_limit:
                logger.warning(
                    f"Rate limit exceeded: client={client_id} "
                    f"rpm={current_rpm}/{rpm_limit}"
                )
                return (
                    False,
                    f"Rate limit exceeded: {current_rpm} requests this minute "
                    f"(limit: {rpm_limit} RPM)",
                )

            logger.debug(
                f"Rate limit: client={client_id} rpm={current_rpm}/{rpm_limit} "
                f"(minute={minute})"
            )

        # --- TPM check (read-only, tokens recorded post-request) ---
        if tpm_limit and tpm_limit > 0:
            tpm_key = _TPM_KEY.format(client_id=client_id, minute=minute)
            current_tpm = int(await r.get(tpm_key) or 0)

            if current_tpm >= tpm_limit:
                logger.warning(
                    f"Rate limit exceeded: client={client_id} "
                    f"tpm={current_tpm}/{tpm_limit}"
                )
                return (
                    False,
                    f"Token rate limit exceeded: {current_tpm} tokens this minute "
                    f"(limit: {tpm_limit} TPM)",
                )

            logger.debug(
                f"Rate limit: client={client_id} tpm={current_tpm}/{tpm_limit} "
                f"(minute={minute})"
            )

        return (True, None)

    except Exception as e:
        # Fail-OPEN: rate limiting is a soft gate, not security
        logger.error(f"Redis error during rate limit check for client={client_id}: {e}")
        return (True, None)


async def record_client_tokens(client_id: str, tokens: int) -> None:
    """Record token usage after request completion.

    Increments the TPM counter for the current minute window.

    Args:
        client_id: The client identifier.
        tokens: Number of tokens consumed.
    """
    if tokens <= 0:
        return

    try:
        r = _get_redis()
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")
        tpm_key = _TPM_KEY.format(client_id=client_id, minute=minute)

        new_total = await r.incrby(tpm_key, tokens)
        if new_total == tokens:
            await r.expire(tpm_key, _MINUTE_TTL)

        logger.debug(
            f"Rate limit: recorded {tokens} tokens for client={client_id}, "
            f"total={new_total} (minute={minute})"
        )

    except Exception as e:
        # Fail-OPEN: don't break the request if we can't record tokens
        logger.error(
            f"Redis error recording tokens for client={client_id}: {e}"
        )


async def get_client_rate_usage(client_id: str) -> dict[str, int]:
    """Get current rate limit usage for a client.

    Returns:
        Dictionary with current RPM and TPM counters for the current minute.
    """
    try:
        r = _get_redis()
        minute = datetime.now(UTC).strftime("%Y%m%d%H%M")

        rpm_key = _RPM_KEY.format(client_id=client_id, minute=minute)
        tpm_key = _TPM_KEY.format(client_id=client_id, minute=minute)

        rpm_current = int(await r.get(rpm_key) or 0)
        tpm_current = int(await r.get(tpm_key) or 0)

        return {
            "rpm_current": rpm_current,
            "tpm_current": tpm_current,
        }

    except Exception as e:
        logger.error(
            f"Redis error getting rate usage for client={client_id}: {e}"
        )
        return {
            "rpm_current": 0,
            "tpm_current": 0,
        }
