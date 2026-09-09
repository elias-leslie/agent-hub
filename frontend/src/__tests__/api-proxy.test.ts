import { afterEach, describe, expect, it, vi } from 'vitest'

vi.mock('@/lib/api-config', () => ({
  buildInternalHeaders: () => ({ 'X-Client-Id': 'agent-hub-dashboard' }),
  getApiBaseUrl: () => 'http://backend.test',
}))

import { PUT } from '@/app/api/proxy/[...path]/route'

afterEach(() => vi.unstubAllGlobals())

describe('dashboard proxy project scope', () => {
  it('preserves the selected project when saving overrides', async () => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ overrides: [] }))
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
      {
        params: Promise.resolve({
          path: ['runtime-context', 'agent_startup', 'overrides'],
        }),
      },
    )
    expect(response.status).toBe(200)
    expect(fetch.mock.calls[0][0]).toBe(
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
      {
        params: Promise.resolve({
          path: ['runtime-context', 'agent_startup', 'overrides'],
        }),
      },
    )
    expect(response.status).toBe(401)
    expect(fetch).not.toHaveBeenCalled()
  })
})
