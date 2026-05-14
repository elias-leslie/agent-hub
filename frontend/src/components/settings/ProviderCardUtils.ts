export function timeAgo(dateStr: string): string {
  const seconds = Math.floor((Date.now() - new Date(dateStr).getTime()) / 1000)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

/** Convert a unix epoch timestamp (seconds) to relative time string */
export function unixTimeAgo(epochSeconds: number): string {
  const seconds = Math.floor(Date.now() / 1000 - epochSeconds)
  if (seconds < 60) return 'just now'
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  return `${days}d ago`
}

export function formatDuration(totalSeconds: number): string {
  const days = Math.floor(totalSeconds / 86400)
  if (days > 30) return `${Math.floor(days / 30)} months`
  if (days > 0) return `${days}d`
  const hours = Math.floor(totalSeconds / 3600)
  if (hours > 0) return `${hours}h`
  const minutes = Math.floor(totalSeconds / 60)
  return `${minutes}m`
}

// Re-exported from canonical location
export { formatLatency } from '@/lib/formatters'

export const OAUTH_STATUS = {
  AUTHENTICATED: 'authenticated',
  EXPIRED: 'expired',
  NOT_CONFIGURED: 'not_configured',
} as const

export const AUTH_PREFERENCE = {
  OAUTH: 'oauth',
  API_KEY: 'api_key',
} as const

export const MANUAL_PASTE = {
  DEFAULT_HINT:
    "If the popup didn't redirect, copy the URL from the address bar",
  DEFAULT_PLACEHOLDER: 'https://localhost/...?code=...',
} as const
