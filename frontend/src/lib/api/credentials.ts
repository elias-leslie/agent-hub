/**
 * Credentials API
 */

import { fetchApi, getApiBaseUrl } from '../api-config'

const API_BASE = `${getApiBaseUrl()}/api`

export interface Credential {
  id: number
  provider: string
  credential_type: string
  value_masked: string
  created_at: string
  updated_at: string
}

export interface CredentialListResponse {
  credentials: Credential[]
  total: number
}

export interface CredentialCreate {
  provider: string
  credential_type: string
  value: string
}

export async function fetchCredentials(
  provider?: string,
): Promise<CredentialListResponse> {
  const url = provider
    ? `${API_BASE}/credentials?provider=${provider}`
    : `${API_BASE}/credentials`
  const response = await fetchApi(url)
  if (!response.ok) {
    throw new Error(`Credentials fetch failed: ${response.status}`)
  }
  return response.json()
}

export async function createCredential(
  data: CredentialCreate,
): Promise<Credential> {
  const response = await fetchApi(`${API_BASE}/credentials`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(
      error.detail || `Create credential failed: ${response.status}`,
    )
  }
  return response.json()
}

export async function updateCredential(
  id: number,
  value: string,
): Promise<Credential> {
  const response = await fetchApi(`${API_BASE}/credentials/${id}`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ value }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(
      error.detail || `Update credential failed: ${response.status}`,
    )
  }
  return response.json()
}

export async function deleteCredential(id: number): Promise<void> {
  const response = await fetchApi(`${API_BASE}/credentials/${id}`, {
    method: 'DELETE',
  })
  if (!response.ok) {
    throw new Error(`Delete credential failed: ${response.status}`)
  }
}

export interface SetPrimaryCredentialResponse {
  success: boolean
  provider: string
  primary_credential_id: number
}

export async function setPrimaryCredential(
  id: number,
): Promise<SetPrimaryCredentialResponse> {
  const response = await fetchApi(`${API_BASE}/credentials/${id}/set-primary`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(
      error.detail || `Set primary credential failed: ${response.status}`,
    )
  }
  return response.json()
}

export interface ClaudeOAuthStatus {
  status: 'valid' | 'expired' | 'missing'
  expires_at: string | null
  expires_in_seconds: number | null
  scopes: string[]
  subscription_type: string | null
  token_prefix: string | null
}

export async function fetchClaudeOAuthStatus(): Promise<ClaudeOAuthStatus> {
  const response = await fetchApi(`${API_BASE}/credentials/claude-oauth-status`)
  if (!response.ok) {
    throw new Error(`Claude OAuth status fetch failed: ${response.status}`)
  }
  return response.json()
}

// --- OAuth flow API ---

export interface OAuthAuthorizeResponse {
  url: string
  state: string
  uses_callback_server: boolean
}

export interface OAuthStatusResponse {
  provider: string
  oauth_status: 'authenticated' | 'expired' | 'not_configured'
  api_key_status: 'configured' | 'not_configured'
  preferred_auth: 'oauth' | 'api_key'
  email?: string | null
}

export async function startOAuthFlow(
  provider: string,
): Promise<OAuthAuthorizeResponse> {
  const response = await fetchApi(`${API_BASE}/oauth/${provider}/authorize`, {
    method: 'POST',
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(
      error.detail || `OAuth authorize failed: ${response.status}`,
    )
  }
  return response.json()
}

export async function fetchOAuthStatus(
  provider: string,
): Promise<OAuthStatusResponse> {
  const response = await fetchApi(`${API_BASE}/oauth/${provider}/status`)
  if (!response.ok) {
    throw new Error(`OAuth status fetch failed: ${response.status}`)
  }
  return response.json()
}

export interface OAuthExchangeResponse {
  success: boolean
  provider: string
  email?: string | null
  error?: string | null
}

export async function exchangeOAuthCode(
  provider: string,
  codeInput: string,
  state: string,
): Promise<OAuthExchangeResponse> {
  const response = await fetchApi(`${API_BASE}/oauth/${provider}/exchange`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code_input: codeInput, state }),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => ({}))
    throw new Error(error.detail || `OAuth exchange failed: ${response.status}`)
  }
  return response.json()
}
