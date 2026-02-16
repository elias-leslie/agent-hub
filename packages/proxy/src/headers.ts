import type { ProxyConfig } from './config'

/** Standard SSE response headers to prevent buffering. */
export const SSE_HEADERS = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
} as const

/**
 * Build Agent Hub authentication headers from resolved config.
 * Only includes headers with non-empty values.
 */
export function buildAuthHeaders(config: ProxyConfig): Record<string, string> {
  const headers: Record<string, string> = {}
  if (config.requestSource) headers['X-Request-Source'] = config.requestSource
  if (config.clientId) headers['X-Client-Id'] = config.clientId
  if (config.clientSecret) headers['X-Client-Secret'] = config.clientSecret
  return headers
}

/**
 * Build the upstream Agent Hub URL for a given API path.
 *
 * @param config - Resolved proxy config
 * @param path - API path segments (string or array)
 * @param searchParams - Optional query string (without leading '?')
 */
export function buildUpstreamUrl(
  config: ProxyConfig,
  path: string | string[],
  searchParams?: string,
): string {
  const joined = Array.isArray(path) ? path.join('/') : path
  const qs = searchParams ? `?${searchParams}` : ''
  return `${config.agentHubUrl}/api/${joined}${qs}`
}
