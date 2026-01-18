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
 * @param path - WebSocket path (e.g., /api/stream)
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

  // Production
  if (host === PROD_DOMAIN) {
    return `${protocol}//${PROD_API_DOMAIN}${path}`
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
 * Get the SummitFlow API base URL (external service).
 * Used for cross-project features like project list fetching.
 *
 * @returns Full URL for SummitFlow API or null if not available
 */
export function getSummitFlowApiUrl(): string | null {
  if (typeof window === 'undefined') {
    return `http://localhost:${PORTS.summitflow}`
  }

  const host = window.location.hostname

  // Development: localhost or 127.0.0.1
  if (host === 'localhost' || host === '127.0.0.1') {
    return `http://localhost:${PORTS.summitflow}`
  }

  // Production: use SummitFlow API domain
  if (host === PROD_DOMAIN) {
    return `https://${SUMMITFLOW_API_DOMAIN}`
  }

  // Fallback: SummitFlow not available in unknown environments
  return null
}
