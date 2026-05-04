import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

describe('fetchApi', () => {
  const originalEnv = { ...process.env }
  const originalWindow = globalThis.window

  beforeEach(() => {
    vi.resetModules()
    process.env = { ...originalEnv }
  })

  afterEach(() => {
    process.env = originalEnv
    if (originalWindow === undefined) {
      Reflect.deleteProperty(globalThis, 'window')
    } else {
      vi.stubGlobal('window', originalWindow)
    }
    vi.restoreAllMocks()
  })

  it('attaches runtime auth headers for server-side requests', async () => {
    process.env.INTERNAL_SERVICE_SECRET = 'secret-123'
    process.env.AGENT_HUB_DASHBOARD_CLIENT_ID = 'client-123'
    process.env.AGENT_HUB_DASHBOARD_REQUEST_SOURCE = 'agent-hub-dashboard'
    vi.stubGlobal('window', undefined)

    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const { fetchApi } = await import('./api-config')

    await fetchApi('http://localhost:8003/api/sessions')

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8003/api/sessions',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Agent-Hub-Internal': 'secret-123',
          'X-Client-Id': 'client-123',
          'X-Request-Source': 'agent-hub-dashboard',
        }),
      }),
    )
  })

  it('lets explicit caller headers override defaults', async () => {
    process.env.INTERNAL_SERVICE_SECRET = 'secret-123'
    vi.stubGlobal('window', undefined)

    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const { fetchApi } = await import('./api-config')

    await fetchApi('http://localhost:8003/api/sessions', {
      headers: { 'X-Agent-Hub-Internal': 'override' },
    })

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8003/api/sessions',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Agent-Hub-Internal': 'override',
        }),
      }),
    )
  })

  it('builds the same-origin chat completion path for browser requests', async () => {
    vi.stubGlobal('window', {
      location: { hostname: '192.168.8.244' },
    } as Window & typeof globalThis)

    const { getCompleteApiUrl } = await import('./api-config')

    expect(getCompleteApiUrl()).toBe('/api/complete')
  })

  it('uses the built-in dashboard identity when no client id env is set', async () => {
    delete process.env.INTERNAL_SERVICE_SECRET
    delete process.env.AGENT_HUB_DASHBOARD_CLIENT_ID
    delete process.env.NEXT_PUBLIC_AGENT_HUB_DASHBOARD_CLIENT_ID
    vi.stubGlobal('window', undefined)

    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }))
    vi.stubGlobal('fetch', fetchMock)

    const { fetchApi } = await import('./api-config')

    await fetchApi('http://localhost:8003/api/persona')

    expect(fetchMock).toHaveBeenCalledWith(
      'http://localhost:8003/api/persona',
      expect.objectContaining({
        headers: expect.objectContaining({
          'X-Client-Id': 'agent-hub-dashboard',
          'X-Request-Source': 'agent-hub-dashboard',
        }),
      }),
    )
  })
})
