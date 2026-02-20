"""OAuth flow endpoints for Claude, Codex, and Gemini providers.

Handles the browser-based OAuth PKCE flow:
1. Frontend calls POST /api/oauth/{provider}/authorize
2. Backend generates PKCE params, starts temp callback server (Codex/Gemini),
   returns auth URL
3. Frontend opens auth URL in popup AND shows manual paste input
4. **Local path**: callback server receives redirect → tokens stored → popup
   does postMessage("oauth-success") → frontend clears paste UI
5. **Remote path** (or Claude): user copies code/URL → pastes into input →
   frontend calls POST /api/oauth/{provider}/exchange → tokens stored
6. Whichever path completes first wins; the other is cancelled/cleaned up.
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

from app.adapters.claude_auth import (
    create_claude_auth_flow,
    exchange_claude_code,
    parse_claude_auth_input,
)
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
    ANTIGRAVITY_REDIRECT_URI,
    GEMINI_REDIRECT_URI,
    create_antigravity_auth_flow,
    create_gemini_auth_flow,
    discover_project,
    exchange_antigravity_code,
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
    uses_callback_server: bool = Field(False, description="Whether a local callback server is listening")


class OAuthStatusResponse(BaseModel):
    provider: str
    oauth_status: str = Field("not_configured", description="authenticated, expired, or not_configured")
    api_key_status: str = Field("not_configured", description="configured or not_configured")
    preferred_auth: str = Field("api_key", description="oauth or api_key")
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


async def _complete_antigravity_flow(state: str, db: AsyncSession) -> None:
    """Wait for Antigravity OAuth callback, exchange code, store credentials."""
    parsed = urlparse(ANTIGRAVITY_REDIRECT_URI)
    port = parsed.port or 51121
    path = parsed.path

    try:
        code, received_state = await _run_callback_flow(port, path, "antigravity")

        if received_state != state:
            logger.error("Antigravity OAuth state mismatch")
            return

        flow = _pending_flows.get(state)
        if not flow:
            logger.error("Antigravity OAuth flow not found for state")
            return

        code_verifier = flow["code_verifier"]
        creds = await exchange_antigravity_code(code, code_verifier)

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
        await _upsert_credential(db, "antigravity", "oauth_token", token_data)
        if creds.refresh_token:
            await _upsert_credential(db, "antigravity", "refresh_token", creds.refresh_token)

        logger.info("Antigravity OAuth flow completed successfully (project=%s, email=%s)", project_id, email)

    except Exception:
        logger.exception("Antigravity OAuth flow failed")
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

    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"], uses_callback_server=True)


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

    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"], uses_callback_server=True)


@router.post("/antigravity/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_antigravity(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthAuthorizeResponse:
    """Start Antigravity OAuth PKCE flow for Claude model access.

    Uses a different Google OAuth client than Gemini CLI, with additional
    scopes required for the Antigravity endpoint.
    """
    _cleanup_expired_flows()

    if "antigravity" in _active_servers:
        _active_servers["antigravity"].close()
        _active_servers.pop("antigravity", None)

    flow = create_antigravity_auth_flow()

    _pending_flows[flow["state"]] = {
        "provider": "antigravity",
        "code_verifier": flow["code_verifier"],
        "created_at": time.time(),
    }

    task = asyncio.create_task(_complete_antigravity_flow(flow["state"], db))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)

    return OAuthAuthorizeResponse(url=flow["url"], state=flow["state"], uses_callback_server=True)


@router.get("/{provider}/status", response_model=OAuthStatusResponse)
async def get_oauth_status(
    provider: str,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthStatusResponse:
    """Check OAuth authentication status for a provider.

    Returns separate oauth_status and api_key_status so the frontend
    can show the Authenticate button even when an API key exists.
    """
    if provider not in ("claude", "codex", "gemini", "antigravity"):
        raise HTTPException(status_code=400, detail=f"OAuth not supported for provider: {provider}")

    from app.api.preferences import get_preference_value

    cm = get_credential_manager()

    # Check API key status
    api_key = cm.get_api_key(provider)
    api_key_status = "configured" if api_key else "not_configured"

    # Check OAuth token status
    oauth_status = "not_configured"
    email: str | None = None

    if provider == "claude":
        token_json = cm.get("claude", "oauth_token")
        if token_json:
            try:
                data = json.loads(token_json)
                expires_at = data.get("expires_at")
                email = data.get("email")
                if expires_at and time.time() >= expires_at:
                    oauth_status = "expired"
                else:
                    oauth_status = "authenticated"
            except (json.JSONDecodeError, TypeError):
                oauth_status = "authenticated"

    elif provider == "codex":
        oauth_token = cm.get("codex", "oauth_token")
        if oauth_token:
            oauth_status = "authenticated"

    elif provider in ("gemini", "antigravity"):
        token_json = cm.get(provider, "oauth_token")
        if token_json:
            try:
                data = json.loads(token_json)
                expires_at = data.get("expires_at")
                email = data.get("email")
                has_refresh = bool(cm.get(provider, "refresh_token"))
                if expires_at and time.time() >= expires_at and not has_refresh:
                    # Only "expired" if we can't auto-refresh
                    oauth_status = "expired"
                else:
                    oauth_status = "authenticated"
            except (json.JSONDecodeError, TypeError):
                oauth_status = "authenticated"

    # Get preferred auth method
    preferred_auth = await get_preference_value(
        db, f"{provider}_auth_preference", "api_key",
    )

    return OAuthStatusResponse(
        provider=provider,
        oauth_status=oauth_status,
        api_key_status=api_key_status,
        preferred_auth=preferred_auth,
        email=email,
    )


# ---------------------------------------------------------------------------
# Claude authorize endpoint (no callback server)
# ---------------------------------------------------------------------------

@router.post("/claude/authorize", response_model=OAuthAuthorizeResponse)
async def authorize_claude() -> OAuthAuthorizeResponse:
    """Start Claude OAuth PKCE flow.

    Returns an authorization URL. Unlike Codex/Gemini, Claude uses
    Anthropic's public redirect page — no local callback server is needed.
    The user copies the displayed code and pastes it into the frontend.
    """
    _cleanup_expired_flows()

    flow = create_claude_auth_flow()

    _pending_flows[flow["state"]] = {
        "provider": "claude",
        "code_verifier": flow["code_verifier"],
        "created_at": time.time(),
    }

    return OAuthAuthorizeResponse(
        url=flow["url"],
        state=flow["state"],
        uses_callback_server=False,
    )


# ---------------------------------------------------------------------------
# Generic manual exchange endpoint
# ---------------------------------------------------------------------------

class OAuthExchangeRequest(BaseModel):
    code_input: str = Field(..., description="Pasted code or redirect URL")
    state: str = Field(..., description="State from the authorize response")


class OAuthExchangeResponse(BaseModel):
    success: bool
    provider: str
    email: str | None = None
    error: str | None = None


def _parse_codex_input(raw: str) -> tuple[str, str | None]:
    """Parse Codex OAuth input: full URL, code#state, query string, or plain code.

    Returns (code, state_or_none).
    """
    raw = raw.strip()

    # Full redirect URL: http://localhost:1455/auth/callback?code=...&state=...
    if raw.startswith("http"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            return code, state

    # code#state format
    if "#" in raw:
        code, state = raw.split("#", 1)
        return code.strip(), state.strip()

    # Query string: code=...&state=...
    if "code=" in raw:
        params = parse_qs(raw)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            return code, state

    # Plain code
    return raw, None


def _parse_gemini_input(raw: str) -> tuple[str, str | None]:
    """Parse Gemini OAuth input: full redirect URL.

    Returns (code, state_or_none).
    """
    raw = raw.strip()

    if raw.startswith("http"):
        parsed = urlparse(raw)
        params = parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        if code:
            return code, state

    # Plain code fallback
    return raw, None


@router.post("/{provider}/exchange", response_model=OAuthExchangeResponse)
async def exchange_oauth_code(
    provider: str,
    body: OAuthExchangeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OAuthExchangeResponse:
    """Manually exchange an OAuth code/URL for tokens.

    Used when the local callback server is unreachable (remote access)
    or for Claude (which never has a callback server). The user pastes
    the code or redirect URL from the browser.
    """
    if provider not in ("claude", "codex", "gemini", "antigravity"):
        raise HTTPException(status_code=400, detail=f"Exchange not supported for provider: {provider}")

    flow = _pending_flows.get(body.state)
    if not flow:
        return OAuthExchangeResponse(success=False, provider=provider, error="Unknown or expired state")
    if flow["provider"] != provider:
        return OAuthExchangeResponse(success=False, provider=provider, error="State/provider mismatch")

    code_verifier = flow["code_verifier"]

    # Cancel any active callback server for this provider
    if provider in _active_servers:
        _active_servers[provider].close()
        _active_servers.pop(provider, None)

    try:
        email: str | None = None

        if provider == "claude":
            code, _parsed_state = parse_claude_auth_input(body.code_input)
            creds = await exchange_claude_code(code, code_verifier, body.state)

            token_data = json.dumps({
                "access_token": creds.access_token,
                "expires_at": creds.expires_at,
            })
            await _upsert_credential(db, "claude", "oauth_token", token_data)
            if creds.refresh_token:
                await _upsert_credential(db, "claude", "refresh_token", creds.refresh_token)

        elif provider == "codex":
            code, _parsed_state = _parse_codex_input(body.code_input)
            creds = await exchange_codex_code(code, code_verifier)

            await _upsert_credential(db, "codex", "oauth_token", creds.access_token)
            if creds.refresh_token:
                await _upsert_credential(db, "codex", "refresh_token", creds.refresh_token)

        elif provider == "gemini":
            code, _parsed_state = _parse_gemini_input(body.code_input)
            creds = await exchange_gemini_code(code, code_verifier)

            project_id = await discover_project(creds.access_token)
            email = await get_user_email(creds.access_token)

            token_data = json.dumps({
                "access_token": creds.access_token,
                "project_id": project_id,
                "email": email,
                "expires_at": creds.expires_at,
            })
            await _upsert_credential(db, "gemini", "oauth_token", token_data)
            if creds.refresh_token:
                await _upsert_credential(db, "gemini", "refresh_token", creds.refresh_token)

        elif provider == "antigravity":
            code, _parsed_state = _parse_gemini_input(body.code_input)
            creds = await exchange_antigravity_code(code, code_verifier)

            project_id = await discover_project(creds.access_token)
            email = await get_user_email(creds.access_token)

            token_data = json.dumps({
                "access_token": creds.access_token,
                "project_id": project_id,
                "email": email,
                "expires_at": creds.expires_at,
            })
            await _upsert_credential(db, "antigravity", "oauth_token", token_data)
            if creds.refresh_token:
                await _upsert_credential(db, "antigravity", "refresh_token", creds.refresh_token)

        # Invalidate the adapter cache so it picks up the new token
        from app.api.complete.helpers_adapters import invalidate_adapter
        invalidate_adapter(provider)

        logger.info("Manual OAuth exchange succeeded for %s", provider)
        _pending_flows.pop(body.state, None)
        return OAuthExchangeResponse(success=True, provider=provider, email=email)

    except Exception as e:
        logger.exception("Manual OAuth exchange failed for %s", provider)
        return OAuthExchangeResponse(success=False, provider=provider, error=str(e))
