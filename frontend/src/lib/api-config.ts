/**
 * API configuration for Agent Hub frontend.
 *
 * Uses same-origin routing via Next.js rewrites to avoid CORS issues with CF Access:
 * - Development: http://localhost:3003/api/* -> localhost:8003/api/* (rewrite)
 * - Production: https://agent.summitflow.dev/api/* -> localhost:8003/api/* (rewrite)
 *
 * This pattern ensures all API requests go through the same origin as the frontend,
 * with Next.js server-side proxying to the backend. No cross-origin = no CORS.
 */

const PORTS = { frontend: 3003, backend: 8003, summitflow: 8001 }
const PROD_DOMAIN = 'agent.summitflow.dev'
const PROD_API_DOMAIN = 'agentapi.summitflow.dev'
const SUMMITFLOW_API_DOMAIN = 'devapi.summitflow.dev'

/**
 * Get the base URL for Agent Hub backend API calls.
 *
 * Returns empty string for client-side (same-origin via rewrites) or localhost for server-side.
 *
 * @returns Base URL (empty for client-side same-origin, full URL for server-side)
 */
export function getApiBaseUrl(): string {
  // Server-side: use localhost directly (for server components, API routes)
  if (typeof window === 'undefined') {
    return `http://localhost:${PORTS.backend}`
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
    return `ws://localhost:${PORTS.backend}${path}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.hostname

  // Development
  if (host === 'localhost' || host === '127.0.0.1') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  // Production: use same-origin WebSocket via Cloudflare Tunnel path routing
  // Tunnel config routes /api/* and /ws/* paths directly to backend
  if (host === PROD_DOMAIN) {
    return `${protocol}//${PROD_DOMAIN}${path}`
  }

  // Fallback
  return `ws://localhost:${PORTS.backend}${path}`
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
 * Internal header for bypassing access control middleware.
 * The agent-hub dashboard is an internal service and doesn't need
 * client authentication for its own API calls.
 */
export const INTERNAL_HEADERS = {
  'X-Agent-Hub-Internal': 'agent-hub-internal-v1',
}

/**
 * Fetch wrapper that includes internal authentication header.
 * Use this for all API calls from the frontend dashboard.
 *
 * @param url - URL to fetch
 * @param options - Standard fetch options
 * @returns Fetch response
 */
export async function fetchApi(url: string, options: RequestInit = {}): Promise<Response> {
  const headers = {
    ...INTERNAL_HEADERS,
    ...options.headers,
  }
  return fetch(url, { ...options, headers })
}

/**
 * Get the SummitFlow API base URL (external service).
 * Used for cross-project features like project list fetching.
 *
 * Uses same-origin routing via Next.js rewrites (/summitflow-api/* -> localhost:8001/api/*)
 * to avoid CORS issues with CF Access protected environments.
 *
 * @returns Base URL for SummitFlow API or null if not available
 */
export function getSummitFlowApiUrl(): string | null {
  // Server-side: use localhost directly
  if (typeof window === 'undefined') {
    return `http://localhost:${PORTS.summitflow}`
  }

  const host = window.location.hostname

  // Development: localhost or 127.0.0.1
  if (host === 'localhost' || host === '127.0.0.1') {
    return `http://localhost:${PORTS.summitflow}`
  }

  // Production: use same-origin routing via Next.js rewrites
  // Calls to /summitflow-api/* are proxied to localhost:8001/api/*
  if (host === PROD_DOMAIN) {
    return '/summitflow-api'
  }

  // Fallback: SummitFlow not available in unknown environments
  return null
}
