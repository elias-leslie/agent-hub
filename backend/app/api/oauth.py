"""OAuth flow endpoints for Codex and Gemini providers.

Handles the browser-based OAuth PKCE flow:
1. Frontend calls POST /api/oauth/{provider}/authorize
2. Backend generates PKCE params, starts temp callback server, returns auth URL
3. Frontend opens auth URL in popup
4. Provider redirects popup to local callback server
5. Callback server exchanges code for tokens, stores in DB
6. Responds with HTML that does window.opener.postMessage() + window.close()
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Annotated
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.codex_auth import (
    CODEX_REDIRECT_URI,
)
from app.adapters.codex_auth import (
    create_auth_flow as create_codex_auth_flow,
)
from app.adapters.codex_auth import (
    exchange_code as exchange_codex_code,
)
from app.adapters.gemini_auth import (
    GEMINI_REDIRECT_URI,
    create_gemini_auth_flow,
    discover_project,
    exchange_gemini_code,
    get_user_email,
)
from app.db import get_db
from app.services.credential_manager import get_credential_manager
from app.storage.credentials import store_credential_async

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/oauth", tags=["oauth"])

# ---------------------------------------------------------------------------
# In-memory pending flow store (state → flow data, TTL 10 min)
# ---------------------------------------------------------------------------

_pending_flows: dict[str, dict] = {}
_FLOW_TTL = 600  # 10 minutes

# Track active callback servers so we don't start duplicates
_active_servers: dict[str, asyncio.Server] = {}

# Hold references to background tasks to prevent GC
_background_tasks: set[asyncio.Task] = set()  # type: ignore[type-arg]


def _cleanup_expired_flows() -> None:
    """Remove flows older than TTL."""
    now = time.time()
    expired = [k for k, v in _pending_flows.items() if now - v.get("created_at", 0) > _FLOW_TTL]
    for k in expired:
        _pending_flows.pop(k, None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class OAuthAuthorizeResponse(BaseModel):
    url: str = Field(..., description="Authorization URL to open in browser/popup")
    state: str = Field(..., description="State parameter for CSRF validation")


class OAuthStatusResponse(BaseModel):
    status: str = Field(..., description="authenticated, expired, or not_configured")
    provider: str
    email: str | None = None


# ---------------------------------------------------------------------------
# Success/error HTML templates for the popup callback
# ---------------------------------------------------------------------------

_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Authentication Successful</title>
<style>
  body { font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; }
  .card { text-align: center; padding: 2rem; border-radius: 12px;
          background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  h2 { color: #16a34a; margin: 0 0 0.5rem; }
  p { color: #64748b; margin: 0; }
</style></head>
<body><div class="card">
  <h2>Authenticated</h2>
  <p>{provider} connected. This window will close automatically.</p>
</div>
<script>
  if (window.opener) {{
    window.opener.postMessage({{ type: "oauth-success", provider: "{provider}" }}, "*");
  }}
  setTimeout(() => window.close(), 1500);
</script></body></html>"""

_ERROR_HTML = """<!DOCTYPE html>
<html><head><title>Authentication Failed</title>
<style>
  body { font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; }
  .card { text-align: center; padding: 2rem; border-radius: 12px;
          background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
  h2 { color: #dc2626; margin: 0 0 0.5rem; }
  p { color: #64748b; margin: 0; }
</style></head>
<body><div class="card">
  <h2>Authentication Failed</h2>
  <p>{error}</p>
</div>
<script>
  if (window.opener) {{
    window.opener.postMessage({{ type: "oauth-error", provider: "{provider}", error: "{error}" }}, "*");
  }}
  setTimeout(() => window.close(), 5000);
</script></body></html>"""


# ---------------------------------------------------------------------------
# Temporary callback server
# ---------------------------------------------------------------------------

async def _start_callback_server(
    port: int,
    path: str,
    provider: str,
    on_callback: asyncio.Future[tuple[str, str]],
) -> asyncio.Server | None:
    """Start a temporary HTTP server to receive the OAuth callback.

    The server listens on 127.0.0.1:{port} and waits for a GET request
    to {path} with ?code=...&state=... query parameters. It resolves
    ``on_callback`` with (code, state) and then shuts down.

    Returns the server instance, or None if the port is already in use.
    """
    async def handle_connection(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            request_line = await asyncio.wait_for(reader.readline(), timeout=30)
            request_str = request_line.decode("utf-8", errors="replace").strip()

            # Parse: GET /path?code=xxx&state=yyy HTTP/1.1
            parts = request_str.split(" ")
            if len(parts) < 2:
                writer.close()
                return

            url = urlparse(parts[1])
            params = parse_qs(url.query)

            code = params.get("code", [None])[0]
            state = params.get("state", [None])[0]
            error = params.get("error", [None])[0]

            if url.path == path and code and state:
                # Success — resolve the future and respond with HTML
                if not on_callback.done():
                    on_callback.set_result((code, state))
                html = _SUCCESS_HTML.format(provider=provider)
            elif error:
                err_desc = params.get("error_description", [error])[0]
                if not on_callback.done():
                    on_callback.set_exception(RuntimeError(f"OAuth error: {err_desc}"))
                html = _ERROR_HTML.format(provider=provider, error=err_desc)
            else:
                html = _ERROR_HTML.format(provider=provider, error="Missing code or state parameter")

            response = (
                f"HTTP/1.1 200 OK\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(html.encode())}\r\n"
                f"Connection: close\r\n\r\n"
                f"{html}"
            )
            writer.write(response.encode())
            await writer.drain()
        except Exception as e:
            logger.warning("Callback handler error: %s", e)
        finally:
            writer.close()

    try:
        server = await asyncio.start_server(handle_connection, "127.0.0.1", port)
        return server
    except OSError as e:
        logger.warning("Cannot start callback server on port %d: %s", port, e)
        return None


async def _run_callback_flow(
    port: int,
    path: str,
    provider: str,
    timeout: float = 300,
) -> tuple[str, str]:
    """Start callback server, wait for callback, return (code, state).

    Raises TimeoutError if no callback is received within ``timeout`` seconds.
    """
    loop = asyncio.get_event_loop()
    callback_future: asyncio.Future[tuple[str, str]] = loop.create_future()

    server = await _start_callback_server(port, path, provider, callback_future)
    if server is None:
        raise RuntimeError(f"Port {port} is already in use")

    # Track the active server
    _active_servers[provider] = server

    try:
        code, state = await asyncio.wait_for(callback_future, timeout=timeout)
        return code, state
    except TimeoutError:
        raise TimeoutError(f"OAuth callback timed out after {timeout}s") from None
    finally:
        server.close()
        await server.wait_closed()
        _active_servers.pop(provider, None)


# ---------------------------------------------------------------------------
# Credential upsert helper
# ---------------------------------------------------------------------------

async def _upsert_credential(
    db: AsyncSession,
    provider: str,
    credential_type: str,
    value: str,
) -> None:
    """Store or update a credential in the DB and refresh the cache."""
    from app.storage.credentials import list_credentials_async, update_credential_async

    # Check if credential already exists
    existing = await list_credentials_async(db, provider=provider)
    for cred in existing:
        if cred.credential_type == credential_type:
            await update_credential_async(db, cred.id, value)
            get_credential_manager().set(provider, credential_type, value)
            return

    # Create new
    await store_credential_async(db, provider=provider, credential_type=credential_type, value=value)
    get_credential_manager().set(provider, credential_type, value)


# ---------------------------------------------------------------------------
# Background OAuth completion task
# ---------------------------------------------------------------------------

async def _complete_codex_flow(state: str, db: AsyncSession) -> None:
    """Wait for Codex OAuth callback, exchange code, store credentials."""
    parsed = urlparse(CODEX_REDIRECT_URI)
    port = parsed.port or 1455
    path = parsed.path

    try:
        code, received_state = await _run_callback_flow(port, path, "codex")

        if received_state != state:
            logger.error("Codex OAuth state mismatch")
            return

        flow = _pending_flows.get(state)
        if not flow:
            logger.error("Codex OAuth flow not found for state")
            return

        code_verifier = flow["code_verifier"]
        creds = await exchange_codex_code(code, code_verifier)

        # Store tokens
        await _upsert_credential(db, "codex", "oauth_token", creds.access_token)
        if creds.refresh_token:
            await _upsert_credential(db, "codex", "refresh_token", creds.refresh_token)

        logger.info("Codex OAuth flow completed successfully")

    except Exception:
        logger.exception("Codex OAuth flow failed")
    finally:
        _pending_flows.pop(state, None)


async def _complete_gemini_flow(state: str, db: AsyncSession) -> None:
    """Wait for Gemini OAuth callback, exchange code, store credentials."""
    parsed = urlparse(GEMINI_REDIRECT_URI)
    port = parsed.port or 8085
    path = parsed.path

    try:
        code, received_state = await _run_callback_flow(port, path, "gemini")

        if received_state != state:
            logger.error("Gemini OAuth state mismatch")
            return

        flow = _pending_flows.get(state)
        if not flow:
            logger.error("Gemini OAuth flow not found for state")
            return

        code_verifier = flow["code_verifier"]
        creds = await exchange_gemini_code(code, code_verifier)

        # Discover project and email
        project_id = await discover_project(creds.access_token)
        email = await get_user_email(creds.access_token)

        # Store as JSON blob with metadata
        token_data = json.dumps({
            "access_token": creds.access_token,
            "project_id": project_id,
            "email": email,
            "expires_at": creds.expires_at,
        })
        await _upsert_credential(db, "gemini", "oauth_token", token_data)
        if creds.refresh_token:
            await _upsert_credential(db, "gemini", "refresh_token", creds.refresh_token)

        logger.info("Gemini OAuth flow completed successfully (project=%s, email=%s)", project_id, email)

    except Exception:
        logger.exception("Gemini OAuth flow failed")
    finally:
        _pending_flows.pop(state, None)


# ---------------------------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------------------------

@router.post("/codex/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_codex(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthAuthorizeResponse:
    """Start Codex OAuth PKCE flow.

    Returns an authorization URL. The backend starts a temporary callback
    server on localhost:1455 to receive the OAuth redirect.
    """
    _cleanup_expired_flows()

    # Stop any existing callback server for this provider
    if "codex" in _active_servers:
        _active_servers["codex"].close()
        _active_servers.pop("codex", None)

    flow = create_codex_auth_flow()

    _pending_flows[flow["state"]] = {
        "provider": "codex",
        "code_verifier": flow["code_verifier"],
        "created_at": time.time(),
    }

    # Start background task to wait for callback
    task = asyncio.create_task(_complete_codex_flow(flow["state"], db))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"])


@router.post("/gemini/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_gemini(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthAuthorizeResponse:
    """Start Gemini OAuth PKCE flow.

    Returns an authorization URL. The backend starts a temporary callback
    server on localhost:8085 to receive the OAuth redirect.
    """
    _cleanup_expired_flows()

    if "gemini" in _active_servers:
        _active_servers["gemini"].close()
        _active_servers.pop("gemini", None)

    flow = create_gemini_auth_flow()

    _pending_flows[flow["state"]] = {
        "provider": "gemini",
        "code_verifier": flow["code_verifier"],
        "created_at": time.time(),
    }

    task = asyncio.create_task(_complete_gemini_flow(flow["state"], db))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"])


@router.get("/{provider}/status", response_model=OAuthStatusResponse)
async def get_oauth_status(provider: str) -> OAuthStatusResponse:
    """Check OAuth authentication status for a provider."""
    if provider not in ("codex", "gemini"):
        raise HTTPException(status_code=400, detail=f"OAuth not supported for provider: {provider}")

    cm = get_credential_manager()

    if provider == "codex":
        token = cm.get("codex", "oauth_token") or cm.get_api_key("codex")
        if not token:
            return OAuthStatusResponse(status="not_configured", provider=provider)
        return OAuthStatusResponse(status="authenticated", provider=provider)

    if provider == "gemini":
        token_json = cm.get("gemini", "oauth_token")
        if not token_json:
            # Fall back to API key check
            api_key = cm.get_api_key("gemini")
            if api_key:
                return OAuthStatusResponse(status="authenticated", provider=provider)
            return OAuthStatusResponse(status="not_configured", provider=provider)

        try:
            data = json.loads(token_json)
            expires_at = data.get("expires_at")
            if expires_at and time.time() >= expires_at:
                return OAuthStatusResponse(
                    status="expired", provider=provider, email=data.get("email"),
                )
            return OAuthStatusResponse(
                status="authenticated", provider=provider, email=data.get("email"),
            )
        except (json.JSONDecodeError, TypeError):
            return OAuthStatusResponse(status="authenticated", provider=provider)

    return OAuthStatusResponse(status="not_configured", provider=provider)
