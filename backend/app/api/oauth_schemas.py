"""Schemas and HTML templates for the OAuth flow."""

from __future__ import annotations

from pydantic import BaseModel, Field


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


class OAuthExchangeRequest(BaseModel):
    code_input: str = Field(..., description="Pasted code or redirect URL")
    state: str = Field(..., description="State from the authorize response")


class OAuthExchangeResponse(BaseModel):
    success: bool
    provider: str
    email: str | None = None
    error: str | None = None


_SUCCESS_HTML = """<!DOCTYPE html>
<html><head><title>Authentication Successful</title>
<style>
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; }}
  .card {{ text-align: center; padding: 2rem; border-radius: 12px;
          background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  h2 {{ color: #16a34a; margin: 0 0 0.5rem; }}
  p {{ color: #64748b; margin: 0; }}
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
  body {{ font-family: system-ui, sans-serif; display: flex; align-items: center;
         justify-content: center; min-height: 100vh; margin: 0; background: #f8fafc; }}
  .card {{ text-align: center; padding: 2rem; border-radius: 12px;
          background: white; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  h2 {{ color: #dc2626; margin: 0 0 0.5rem; }}
  p {{ color: #64748b; margin: 0; }}
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
