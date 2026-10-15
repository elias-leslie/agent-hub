/**
 * Refuse requests from other sites before Next.js sees them.
 *
 * The dashboard treats a loopback caller as the owner and the API proxy adds
 * the internal secret, so without this any page open in the owner's browser
 * could POST to http://localhost:3003/api/... and change agents or settings.
 * - Host must name this server (loopback or a public dashboard origin), which
 *   defeats DNS rebinding (a rebound evil.example still sends its own Host).
 * - POST/PUT/PATCH/DELETE and WebSocket upgrades from a browser must come from
 *   one of our own origins. Clients that send neither Origin nor
 *   Sec-Fetch-Site (curl, agents, cloudflared health checks) are unaffected.
 */

const LOOPBACK_HOSTS = new Set(['localhost', '127.0.0.1', '[::1]'])
const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS'])
const SAME_SITE_FETCH = new Set(['same-origin', 'none'])

/**
 * Our own browser origins: loopback on the serving port plus the public
 * dashboard origins (AGENT_HUB_PUBLIC_ORIGINS, comma-separated).
 * @param {number} port
 * @param {Record<string, string | undefined>} env
 * @returns {Set<string>}
 */
export function allowedOrigins(port, env = process.env) {
  const extra = (env.AGENT_HUB_PUBLIC_ORIGINS ?? 'https://agent.summitflow.dev')
    .split(',')
    .map((origin) => origin.trim().replace(/\/+$/, ''))
    .filter(Boolean)
  return new Set([
    ...[...LOOPBACK_HOSTS].map((host) => `http://${host}:${port}`),
    ...extra,
  ])
}

/**
 * Why a request must be refused, or null to let it through.
 * @param {{ method?: string, headers: Record<string, string | string[] | undefined>, upgrade?: boolean }} request
 * @param {Set<string>} origins from allowedOrigins()
 * @returns {{ status: number, error: string } | null}
 */
export function refusal({ method, headers, upgrade = false }, origins) {
  if (!isAllowedHost(header(headers.host), origins)) {
    return { status: 400, error: 'host_not_allowed' }
  }
  if (!upgrade && SAFE_METHODS.has((method ?? 'GET').toUpperCase())) return null
  const origin = header(headers.origin)
  if (origin !== undefined) {
    return origins.has(origin)
      ? null
      : { status: 403, error: 'origin_not_allowed' }
  }
  const site = header(headers['sec-fetch-site'])
  if (site !== undefined && !SAME_SITE_FETCH.has(site)) {
    return { status: 403, error: 'origin_not_allowed' }
  }
  return null
}

/**
 * @param {string | undefined} host
 * @param {Set<string>} origins
 */
function isAllowedHost(host, origins) {
  const name = hostname(host)
  if (!name) return false
  if (LOOPBACK_HOSTS.has(name)) return true
  for (const origin of origins) {
    if (hostname(origin.replace(/^[a-z]+:\/\//, '')) === name) return true
  }
  return false
}

/** @param {string | undefined} authority */
function hostname(authority) {
  if (!authority) return undefined
  try {
    return new URL(`http://${authority}`).hostname.toLowerCase()
  } catch {
    return undefined
  }
}

/** @param {string | string[] | undefined} value */
function header(value) {
  return Array.isArray(value) ? value[0] : value
}
