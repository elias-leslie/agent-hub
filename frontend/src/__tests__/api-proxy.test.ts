import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-config', () => ({
  buildInternalHeaders: () => ({
    'X-Client-Id': 'agent-hub-dashboard',
    'X-Agent-Hub-Internal': 'test-secret',
  }),
  getApiBaseUrl: () => 'http://backend.test',
}))

import { GET, POST, PUT } from '@/app/api/proxy/[...path]/route'

afterEach(() => vi.unstubAllGlobals())

const me = (isOwner: boolean) => Response.json({ is_owner: isOwner })
const ctx = (path: string[]) => ({ params: Promise.resolve({ path }) })

describe('dashboard proxy project scope', () => {
  it('preserves the selected project when saving overrides', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(me(true))
      .mockResolvedValueOnce(Response.json({ overrides: [] }))
    vi.stubGlobal('fetch', fetch)
    const response = await PUT(
      new Request(
        'http://dashboard.test/api/runtime-context/agent_startup/overrides?project_id=ominull',
        {
          method: 'PUT',
          headers: {
            'X-Client-Id': 'agent-hub-dashboard',
            'X-Request-Source': 'agent-hub-dashboard',
          },
          body: JSON.stringify({ overrides: [] }),
        },
      ),
      ctx(['runtime-context', 'agent_startup', 'overrides']),
    )
    expect(response.status).toBe(200)
    expect(fetch.mock.calls[1][0]).toBe(
      'http://backend.test/api/runtime-context/agent_startup/overrides?project_id=ominull',
    )
  })

  it('still rejects non-dashboard clients', async () => {
    const fetch = vi.fn()
    vi.stubGlobal('fetch', fetch)
    const response = await PUT(
      new Request(
        'http://dashboard.test/api/runtime-context/agent_startup/overrides',
        { method: 'PUT' },
      ),
      ctx(['runtime-context', 'agent_startup', 'overrides']),
    )
    expect(response.status).toBe(401)
    expect(fetch).not.toHaveBeenCalled()
  })
})

describe('dashboard proxy caller identity', () => {
  it('forwards the Access identity and refuses a non-owner before adding the secret', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(me(false))
    vi.stubGlobal('fetch', fetch)
    const response = await GET(
      new Request('http://localhost:3003/api/proxy/sessions', {
        headers: {
          'cf-access-jwt-assertion': 'jwt-1',
          cookie: 'CF_Authorization=jwt-1',
          'x-agent-hub-client-address': '203.0.113.5',
        },
      }),
      ctx(['sessions']),
    )
    expect(response.status).toBe(403)
    expect(fetch).toHaveBeenCalledTimes(1)
    const [url, init] = fetch.mock.calls[0]
    expect(url).toBe('http://backend.test/api/auth/me')
    const headers = init.headers as Headers
    expect(headers.get('Cf-Access-Jwt-Assertion')).toBe('jwt-1')
    expect(headers.get('Cookie')).toBe('CF_Authorization=jwt-1')
    expect(headers.get('X-Agent-Hub-Client-Address')).toBe('203.0.113.5')
    expect(headers.get('X-Agent-Hub-Internal')).toBeNull()
  })

  it('proxies an owner with the internal secret', async () => {
    const fetch = vi
      .fn()
      .mockResolvedValueOnce(me(true))
      .mockResolvedValueOnce(Response.json({ ok: true }))
    vi.stubGlobal('fetch', fetch)
    const response = await GET(
      new Request('http://localhost:3003/api/proxy/sessions?limit=5', {
        headers: { 'x-agent-hub-owner-token': 'tok' },
      }),
      ctx(['sessions']),
    )
    expect(response.status).toBe(200)
    const [url, init] = fetch.mock.calls[1]
    expect(url).toBe('http://backend.test/api/sessions?limit=5')
    const headers = init.headers as Headers
    expect(headers.get('X-Agent-Hub-Internal')).toBe('test-secret')
    // The upstream call carries the caller's own identity too, so owner-only routes judge the real caller.
    expect(headers.get('X-Agent-Hub-Owner-Token')).toBe('tok')
  })

  it('marks a request without a stamped client address as unknown', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(me(false))
    vi.stubGlobal('fetch', fetch)
    await GET(
      new Request('http://localhost:3003/api/proxy/sessions', {
        headers: { host: 'localhost', 'x-forwarded-for': '127.0.0.1' },
      }),
      ctx(['sessions']),
    )
    const headers = fetch.mock.calls[0][1].headers as Headers
    expect(headers.get('X-Agent-Hub-Client-Address')).toBe('unknown')
    expect(headers.get('X-Forwarded-Host')).toBeNull()
  })

  it('forwards the owner token to the identity check', async () => {
    const fetch = vi.fn().mockResolvedValueOnce(me(false))
    vi.stubGlobal('fetch', fetch)
    await GET(
      new Request('http://localhost:3003/api/proxy/sessions', {
        headers: { 'x-agent-hub-owner-token': 'tok' },
      }),
      ctx(['sessions']),
    )
    const headers = fetch.mock.calls[0][1].headers as Headers
    expect(headers.get('X-Agent-Hub-Owner-Token')).toBe('tok')
  })

  it('returns 503 when the identity check cannot run', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new Error('down'))
    vi.stubGlobal('fetch', fetch)
    const response = await POST(
      new Request('http://localhost:3003/api/proxy/complete', {
        method: 'POST',
        body: '{}',
      }),
      ctx(['complete']),
    )
    expect(response.status).toBe(503)
    expect(fetch).toHaveBeenCalledTimes(1)
  })
})
