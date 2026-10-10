import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'

const SW_SOURCE = readFileSync(
  path.resolve(__dirname, '../../public/sw.js'),
  'utf8',
)
const ORIGIN = 'https://hub.example.test'

type Listener = (event: Record<string, unknown>) => void

function loadServiceWorker(
  fetchImpl: (...args: unknown[]) => Promise<unknown>,
) {
  const listeners: Record<string, Listener> = {}
  const put = vi.fn()
  const self = {
    location: new URL(`${ORIGIN}/sw.js`),
    addEventListener: (type: string, listener: Listener) => {
      listeners[type] = listener
    },
    skipWaiting: vi.fn(),
    clients: { claim: vi.fn() },
  }
  const caches = {
    match: vi.fn().mockResolvedValue(undefined),
    open: vi.fn().mockResolvedValue({ put }),
    keys: vi.fn().mockResolvedValue([]),
  }
  new Function('self', 'caches', 'fetch', SW_SOURCE)(self, caches, fetchImpl)
  return { listeners, put, self }
}

async function fetchStaticAsset(responseUrl: string) {
  const response = {
    ok: true,
    redirected: true,
    url: responseUrl,
    clone: () => ({ cloned: true }),
  }
  const { listeners, put } = loadServiceWorker(() => Promise.resolve(response))
  let pending: Promise<unknown> = Promise.resolve()
  listeners.fetch({
    request: {
      url: `${ORIGIN}/static/app.js`,
      method: 'GET',
      headers: new Headers(),
    },
    respondWith: (value: Promise<unknown>) => {
      pending = value
    },
  })
  await pending
  await new Promise((resolve) => setTimeout(resolve, 0))
  return put
}

describe('service worker', () => {
  it('skips caching responses redirected to a Cloudflare Access host', async () => {
    expect(
      await fetchStaticAsset(
        'https://team.cloudflareaccess.com/cdn-cgi/access/login',
      ),
    ).not.toHaveBeenCalled()
  })

  it('matches the Cloudflare Access hostname, not a URL substring', async () => {
    const put = await fetchStaticAsset(
      `${ORIGIN}/static/app.js?next=cloudflareaccess.com`,
    )
    expect(put).toHaveBeenCalledTimes(1)
    const lookalike = await fetchStaticAsset(
      'https://cloudflareaccess.com.evil.test/static/app.js',
    )
    expect(lookalike).toHaveBeenCalledTimes(1)
  })

  it('honours SKIP_WAITING only from same-origin clients', () => {
    const { listeners, self } = loadServiceWorker(() => Promise.resolve({}))
    self.skipWaiting.mockClear()
    listeners.message({
      data: { type: 'SKIP_WAITING' },
      source: { url: 'https://evil.test/' },
    })
    listeners.message({ data: { type: 'SKIP_WAITING' }, source: null })
    expect(self.skipWaiting).not.toHaveBeenCalled()
    listeners.message({
      data: { type: 'SKIP_WAITING' },
      source: { url: `${ORIGIN}/agents` },
    })
    expect(self.skipWaiting).toHaveBeenCalledTimes(1)
  })
})
