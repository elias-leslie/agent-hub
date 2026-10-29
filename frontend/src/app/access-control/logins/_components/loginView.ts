import type { AgentLogin } from '@/lib/api/lab-credentials'

export type SortField =
  | 'target'
  | 'actor'
  | 'kind'
  | 'fields'
  | 'login_url'
  | 'status'
  | 'updated_at'

export type KindFilter =
  | 'all'
  | 'account'
  | 'synthetic'
  | 'temporary'
  | 'unreadable'

export const KIND_LABEL: Record<string, string> = {
  account: 'Real login',
  synthetic: 'Test login',
  temporary: 'Temporary',
}

const FIELD_LABEL: Record<string, string> = {
  totp_secret: '2FA',
}

/** Field names for the table, without the login URL, which has its own column. */
export function fieldSummary(login: AgentLogin): string {
  return login.fields
    .filter((name) => name !== 'login_url')
    .map((name) => FIELD_LABEL[name] ?? name)
    .join(', ')
}

export function kindLabel(login: AgentLogin): string {
  return login.undecodable ? 'Unreadable' : (KIND_LABEL[login.kind ?? ''] ?? '')
}

/** Only http(s) addresses become links; anything else shows as plain text. */
export function safeLoginUrl(value: string | null): URL | null {
  if (!value) return null
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url : null
  } catch {
    return null
  }
}

export type LoginStatus =
  | { state: 'unreadable' }
  | { state: 'expired'; at: string }
  | { state: 'expires'; at: string }
  | { state: 'active' }

export function loginStatus(login: AgentLogin): LoginStatus {
  if (login.undecodable) return { state: 'unreadable' }
  if (login.expires_at) {
    return {
      state: login.expired ? 'expired' : 'expires',
      at: login.expires_at,
    }
  }
  return { state: 'active' }
}

// Sort key per column; null sorts last in either direction.
function sortKey(login: AgentLogin, field: SortField): string | number | null {
  switch (field) {
    case 'target':
      return login.target
    case 'actor':
      return login.actor
    case 'kind':
      return login.undecodable ? 'zzz' : (login.kind ?? null)
    case 'fields':
      return login.undecodable ? null : fieldSummary(login)
    case 'login_url':
      return safeLoginUrl(login.login_url)?.host ?? login.login_url
    case 'status': {
      const status = loginStatus(login)
      if (status.state === 'unreadable') return 0
      if (status.state === 'expired') return 1
      if (status.state === 'expires') return 2
      return 3
    }
    case 'updated_at':
      return login.updated_at ? Date.parse(login.updated_at) : null
  }
}

export function sortLogins(
  logins: AgentLogin[],
  field: SortField,
  direction: 'asc' | 'desc',
): AgentLogin[] {
  const sign = direction === 'asc' ? 1 : -1
  return [...logins].sort((a, b) => {
    const left = sortKey(a, field)
    const right = sortKey(b, field)
    if (left === null || right === null) {
      if (left === right) return 0
      return left === null ? 1 : -1
    }
    const order =
      typeof left === 'number' && typeof right === 'number'
        ? left - right
        : String(left).localeCompare(String(right), undefined, {
            numeric: true,
            sensitivity: 'base',
          })
    return (
      sign * order ||
      a.target.localeCompare(b.target) ||
      a.actor.localeCompare(b.actor)
    )
  })
}

export function filterLogins(
  logins: AgentLogin[],
  {
    text,
    kind,
    showExpired,
  }: { text: string; kind: KindFilter; showExpired: boolean },
): AgentLogin[] {
  const needle = text.trim().toLowerCase()
  return logins.filter((login) => {
    if (!showExpired && login.expired) return false
    if (
      kind === 'unreadable'
        ? !login.undecodable
        : kind !== 'all' && login.kind !== kind
    ) {
      return false
    }
    if (!needle) return true
    return [
      login.target,
      login.actor,
      kindLabel(login),
      fieldSummary(login),
      login.login_url ?? '',
    ]
      .join(' ')
      .toLowerCase()
      .includes(needle)
  })
}

const DEFAULT_PORT: Record<string, string> = { 'https:': '443', 'http:': '80' }

/** Same scheme, host and port, as the server judges a site change. */
export function sameOrigin(a: string, b: string): boolean {
  try {
    const left = new URL(a)
    const right = new URL(b)
    const port = (url: URL) => url.port || DEFAULT_PORT[url.protocol] || ''
    return (
      left.protocol === right.protocol &&
      left.hostname === right.hostname &&
      port(left) === port(right)
    )
  } catch {
    return false
  }
}
