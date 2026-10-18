import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act } from 'react'
import { hydrateRoot } from 'react-dom/client'
import { renderToString } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { useDashboardData } from '@/app/dashboard/hooks/useDashboardData'

vi.mock('@/hooks/use-session-events', () => ({
  useSessionEvents: () => ({ events: [] }),
}))

vi.mock('@/lib/api', () => ({
  fetchStatus: vi.fn(() => new Promise(() => {})),
  fetchSessions: vi.fn(() => new Promise(() => {})),
  fetchDashboardStats: vi.fn(() => new Promise(() => {})),
}))

function ProviderCount() {
  const { status, statusLoading } = useDashboardData({ daysRange: 7 })
  if (statusLoading) return <p>loading</p>
  return <p>{status?.providers.length ?? 0} providers</p>
}

function app(client: QueryClient) {
  return (
    <QueryClientProvider client={client}>
      <ProviderCount />
    </QueryClientProvider>
  )
}

describe('dashboard hydration', () => {
  it('matches server HTML when the shell cached status before the page hydrated', async () => {
    const container = document.createElement('div')
    container.innerHTML = renderToString(app(new QueryClient()))

    const client = new QueryClient()
    client.setQueryData(['status'], {
      providers: [{ name: 'claude' }, { name: 'xai' }],
    })
    const recoverable = vi.fn()
    await act(async () => {
      hydrateRoot(container, app(client), {
        onRecoverableError: recoverable,
      })
    })

    expect(recoverable).not.toHaveBeenCalled()
    expect(container.textContent).toBe('2 providers')
  })
})
