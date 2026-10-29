/**
 * Agent logins API (owner only). Values go out in request bodies only; the list
 * returns names and the login URL, never a value.
 */

import { buildApiUrl, fetchApi } from '../api-config'

export type LoginKind = 'account' | 'synthetic' | 'temporary'

export interface AgentLogin {
  reference: string
  target: string
  actor: string
  kind: LoginKind | null
  expires_at: string | null
  expired: boolean
  fields: string[]
  login_url: string | null
  created_at: string | null
  updated_at: string | null
  undecodable: boolean
}

export interface AccountLoginInput {
  username: string
  password: string
  login_url: string
  totp_secret?: string
}

export interface AccountLoginCreate extends AccountLoginInput {
  target: string
  actor: string
}

export interface LoginReplace extends Partial<AccountLoginInput> {
  values?: Record<string, string>
  expires_at?: string | null
}

const BASE = '/api/lab-credentials'

async function failure(response: Response, fallback: string): Promise<Error> {
  const body = await response.json().catch(() => ({}))
  const detail =
    typeof body.detail === 'string'
      ? body.detail
      : typeof body.message === 'string'
        ? body.message
        : null
  return new Error(detail ?? `${fallback} (${response.status})`)
}

export async function fetchAgentLogins(): Promise<AgentLogin[]> {
  const response = await fetchApi(buildApiUrl(BASE))
  if (!response.ok) throw await failure(response, 'Could not load logins')
  return (await response.json()).credentials
}

export async function addAccountLogin(data: AccountLoginCreate): Promise<void> {
  const response = await fetchApi(buildApiUrl(BASE), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!response.ok) throw await failure(response, 'Could not add the login')
}

export async function replaceAgentLogin(
  target: string,
  actor: string,
  data: LoginReplace,
): Promise<void> {
  const response = await fetchApi(
    buildApiUrl(
      `${BASE}/${encodeURIComponent(target)}/${encodeURIComponent(actor)}`,
    ),
    {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    },
  )
  if (!response.ok) throw await failure(response, 'Could not replace the login')
}

export interface LoginEdit {
  set?: Record<string, string>
  remove?: string[]
  /** Omit to keep the expiry; null clears it. */
  expires_at?: string | null
}

export async function editAgentLogin(
  target: string,
  actor: string,
  data: LoginEdit,
): Promise<void> {
  const response = await fetchApi(
    buildApiUrl(
      `${BASE}/${encodeURIComponent(target)}/${encodeURIComponent(actor)}`,
    ),
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(data),
    },
  )
  if (!response.ok) throw await failure(response, 'Could not save the changes')
}

export async function removeAgentLogin(
  target: string,
  actor: string,
): Promise<void> {
  const response = await fetchApi(
    buildApiUrl(
      `${BASE}/${encodeURIComponent(target)}/${encodeURIComponent(actor)}`,
    ),
    { method: 'DELETE' },
  )
  if (!response.ok) throw await failure(response, 'Could not remove the login')
}
