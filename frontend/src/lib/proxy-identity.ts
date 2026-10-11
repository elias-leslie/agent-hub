import { getApiBaseUrl } from '@/lib/api-config'

/**
 * Copy the caller's identity onto an upstream request.
 *
 * The proxy reaches the backend over loopback and adds the internal service
 * secret, so the backend must judge the real caller: forward the Cloudflare
 * Access assertion, the cookie and the client address that server.mjs stamped
 * from the TCP peer (clients cannot set it; Host is never trusted).
 */
export function setIdentityHeaders(
  request: Request,
  headers: Headers,
): Headers {
  const jwt = request.headers.get('cf-access-jwt-assertion')
  const cookie = request.headers.get('cookie')
  if (jwt) headers.set('Cf-Access-Jwt-Assertion', jwt)
  if (cookie) headers.set('Cookie', cookie)
  headers.set(
    'X-Agent-Hub-Client-Address',
    request.headers.get('x-agent-hub-client-address') || 'unknown',
  )
  return headers
}

/**
 * Resolve the caller through the backend and reject anyone who is not an owner.
 * Returns null when the caller is an owner, else the error response to send.
 */
export async function requireOwner(request: Request): Promise<Response | null> {
  try {
    const response = await fetch(`${getApiBaseUrl()}/api/auth/me`, {
      headers: setIdentityHeaders(
        request,
        new Headers({ Accept: 'application/json' }),
      ),
      cache: 'no-store',
    })
    if (response.ok) {
      const me = (await response.json()) as { is_owner?: unknown }
      if (me.is_owner === true) return null
    }
  } catch {
    return Response.json(
      { detail: 'Could not verify Agent Hub identity' },
      { status: 503 },
    )
  }
  return Response.json({ detail: 'Owner access required' }, { status: 403 })
}
