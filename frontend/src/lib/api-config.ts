/**
 * API configuration for Agent Hub frontend.
 *
 * Uses same-origin routing via Next.js rewrites to avoid CORS issues:
 * - Development: http://localhost:3003/api/* -> localhost:8003/api/* (rewrite)
 * - Production: https://your-agent-hub-host.example/api/* -> backend /api/* (rewrite)
 *
 * This pattern ensures all API requests go through the same origin as the frontend,
 * with Next.js server-side proxying to the backend. No cross-origin = no CORS.
 */

export const PORTS = { frontend: 3003, backend: 8003 }
const PROD_DOMAIN = process.env.NEXT_PUBLIC_AGENT_HUB_PROD_DOMAIN || ''
const DEFAULT_DASHBOARD_CLIENT_ID = 'agent-hub-dashboard'

/**
 * Get the base URL for Agent Hub backend API calls.
 *
 * Returns empty string for client-side (same-origin via rewrites) or localhost for server-side.
 *
 * @returns Base URL (empty for client-side same-origin, full URL for server-side)
 */
export function getApiBaseUrl(): string {
  // Server-side: use AGENT_HUB_API_URL env var (set by Docker compose) or localhost fallback
  if (typeof window === 'undefined') {
    return process.env.AGENT_HUB_API_URL || `http://localhost:${PORTS.backend}`
  }

  // Client-side: use same-origin paths (Next.js rewrites handle proxying)
  // All requests go to /api/* on current origin, rewrites proxy to backend
  return ''
}

/**
 * Get WebSocket URL for a given path.
 *
 * Automatically handles ws/wss based on current protocol.
 *
 * IMPORTANT: In production, WebSocket uses same-origin routing via Cloudflare Tunnel
 * path-based rules. This avoids CF Access cookie issues (cookies are subdomain-specific).
 * The Tunnel config routes /api/* and /ws/* paths directly to the backend.
 *
 * @param path - WebSocket path (e.g., /api/stream, /api/voice/ws)
 * @returns Full WebSocket URL
 */
export function getWsUrl(path: string): string {
  if (typeof window === 'undefined') {
    const apiUrl =
      process.env.AGENT_HUB_API_URL || `http://localhost:${PORTS.backend}`
    return apiUrl.replace(/^http/, 'ws') + path
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.hostname

  // Development
  if (host === 'localhost' || host === '127.0.0.1') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  // Production: use same-origin WebSocket when a canonical public host is set.
  if (host === PROD_DOMAIN) {
    return `${protocol}//${PROD_DOMAIN}${path}`
  }

  // Non-local hosts (e.g. Docker): same-origin WS
  return `${protocol}//${window.location.host}${path}`
}

/**
 * Get the base URL for SSE (Server-Sent Events) connections.
 *
 * SSE doesn't work through Next.js rewrites (response gets buffered).
 * In development, connects directly to the backend.
 * In production, uses same-origin (CF Tunnel routes /api/* directly to backend).
 *
 * @returns Base URL for SSE connections
 */
export function getSseBaseUrl(): string {
  if (typeof window === 'undefined') {
    return process.env.AGENT_HUB_API_URL || `http://localhost:${PORTS.backend}`
  }

  const host = window.location.hostname
  if (host === 'localhost' || host === '127.0.0.1') {
    return `http://localhost:${PORTS.backend}`
  }

  // Non-local hosts (e.g. Docker, production): same-origin
  return ''
}

/**
 * Build a full API URL from a path.
 *
 * @param path - API path (e.g., /api/chat/sessions)
 * @returns Full URL
 */
export function buildApiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`
}

/**
 * Get the chat completion endpoint for browser streaming requests.
 *
 * Using the same-origin /api path keeps chat streaming on the authenticated
 * proxy path instead of depending on client-side header injection.
 */
export function getCompleteApiUrl(): string {
  return `${getApiBaseUrl()}/api/complete`
}

export function buildInternalHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}

  if (typeof window !== 'undefined') {
    // Client-side: SSE/WS paths bypass the Next.js proxy (which injects
    // auth headers), so we must include the dashboard client identity
    // directly.  The NEXT_PUBLIC_ prefix makes these available at build time.
    const clientId =
      process.env.NEXT_PUBLIC_AGENT_HUB_DASHBOARD_CLIENT_ID?.trim() ||
      DEFAULT_DASHBOARD_CLIENT_ID
    if (clientId) {
      headers['X-Client-Id'] = clientId
      headers['X-Request-Source'] = 'agent-hub-dashboard'
    }
    return headers
  }

  // Server-side: attach full internal auth headers from the runtime env.
  const internalSecret = process.env.INTERNAL_SERVICE_SECRET?.trim()
  const dashboardClientId =
    process.env.AGENT_HUB_DASHBOARD_CLIENT_ID?.trim() ||
    DEFAULT_DASHBOARD_CLIENT_ID
  const dashboardRequestSource =
    process.env.AGENT_HUB_DASHBOARD_REQUEST_SOURCE?.trim() ||
    'agent-hub-dashboard'

  if (internalSecret) {
    headers['X-Agent-Hub-Internal'] = internalSecret
  }
  if (dashboardClientId) {
    headers['X-Client-Id'] = dashboardClientId
  }
  if (dashboardRequestSource) {
    headers['X-Request-Source'] = dashboardRequestSource
  }

  return headers
}

// Headers for direct SSE/WS connections that bypass the Next.js proxy.
// On the server side, these include the internal auth header from env.
// On the client side, SSE paths should be exempt from auth or routed
// through the proxy.
export const INTERNAL_HEADERS: Record<string, string> = buildInternalHeaders()

/**
 * Fetch wrapper that includes internal authentication header.
 * Use this for all API calls from the frontend dashboard.
 *
 * @param url - URL to fetch
 * @param options - Standard fetch options
 * @returns Fetch response
 */
export async function fetchApi(
  url: string,
  options: RequestInit = {},
): Promise<Response> {
  const headers = {
    ...buildInternalHeaders(),
    ...options.headers,
  }
  return fetch(url, { ...options, headers })
}
