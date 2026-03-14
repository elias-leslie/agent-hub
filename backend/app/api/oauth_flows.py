"""Background OAuth flow completion tasks for each provider."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import CODEX_REDIRECT_URI
from app.adapters.codex_auth import exchange_code as exchange_codex_code
from app.api.oauth_callback import run_callback_flow
from app.api.oauth_store import get_pending_flow, pop_pending_flow
from app.services.credential_upsert import upsert_credential

logger = logging.getLogger(__name__)


async def complete_codex_flow(state: str, db: AsyncSession) -> None:
    """Wait for Codex OAuth callback, exchange code, store credentials."""
    parsed = urlparse(CODEX_REDIRECT_URI)
    port = parsed.port or 1455
    path = parsed.path

    try:
        code, received_state = await run_callback_flow(port, path, "codex")

        if received_state != state:
            logger.error("Codex OAuth state mismatch")
            return

        flow = get_pending_flow(state)
        if not flow:
            logger.error("Codex OAuth flow not found for state")
            return

        creds = await exchange_codex_code(code, str(flow["code_verifier"]))
        await upsert_credential(db, "codex", "oauth_token", creds.access_token)
        if creds.refresh_token:
            await upsert_credential(db, "codex", "refresh_token", creds.refresh_token)
        logger.info("Codex OAuth flow completed successfully")

    except Exception:
        logger.exception("Codex OAuth flow failed")
    finally:
        pop_pending_flow(state)
