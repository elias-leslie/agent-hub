import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import CostsPage from '@/app/costs/page'
import type { SpendItemDetail, SpendOverview } from '@/lib/api/analytics'
import { fetchSpend, fetchSpendItem } from '@/lib/api/analytics'
import { createQueryClientWrapper } from './test-utils'

const nav = vi.hoisted(() => {
  let search = ''
  const listeners = new Set<() => void>()
  return {
    get search() {
      return search
    },
    reset(value = '') {
      search = value
    },
    subscribe(listener: () => void) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    replace: vi.fn((href: string) => {
      search = href.includes('?') ? href.slice(href.indexOf('?') + 1) : ''
      for (const listener of listeners) listener()
    }),
  }
})

vi.mock('next/navigation', async () => {
  const { useSyncExternalStore } = await import('react')
  return {
    usePathname: () => '/costs',
    useRouter: () => ({ replace: nav.replace, push: nav.replace }),
    useSearchParams: () =>
      new URLSearchParams(
        useSyncExternalStore(
          nav.subscribe,
          () => nav.search,
          () => nav.search,
        ),
      ),
  }
})

vi.mock('@/lib/api/analytics', async (original) => ({
  ...(await original<typeof import('@/lib/api/analytics')>()),
  fetchSpend: vi.fn(),
  fetchSpendItem: vi.fn(),
  fetchOpenCodeGoUsage: vi.fn(() => new Promise(() => {})),
}))

vi.mock('@/lib/api', () => ({
  fetchCostAccounting: vi.fn(() => new Promise(() => {})),
}))

const overview: SpendOverview = {
  range: '24h',
  start: '2026-10-17T15:00:00Z',
  end: '2026-10-18T15:00:00Z',
  bucket_seconds: 3600,
  selected_bucket: null,
  summary: {
    rate_per_hour: 8.4,
    rate_typical: 3.65,
    rate_ratio: 2.3,
    today: 127,
    today_typical: 66.9,
    today_ratio: 1.9,
    week: 1938,
    week_typical: null,
    week_ratio: null,
    data_since: '2026-09-20T00:00:00Z',
  },
  chart: [
    { start: '2026-10-18T13:00:00Z', interactive: 5, routine: 1, other: 0 },
    { start: '2026-10-18T14:00:00Z', interactive: 3, routine: 0.5, other: 0 },
  ],
  total_usd: 9.5,
  unpriced_calls: 2,
  item_count: 2,
  items: [
    {
      key: 'session:claude:abc',
      name: 'Fix the cost page',
      kind: 'interactive',
      project: 'agent-hub',
      usd: 8,
      share: 0.84,
      tokens: 4_200_000,
      calls: 40,
      spark: [5, 3],
    },
    {
      key: 'job:nightshift.planner',
      name: 'nightshift.planner',
      kind: 'routine',
      project: 'nightshift',
      usd: 1.5,
      share: 0.16,
      tokens: 90_000,
      calls: 12,
      spark: [1, 0.5],
    },
  ],
  filters: {
    project: ['agent-hub', 'nightshift'],
    model: ['claude-opus-5-5'],
    kind: ['interactive', 'routine'],
  },
  coverage: {
    percent: 94.1,
    sessions: 34,
    captured: 32,
    uncaptured: [{ source: 'agent', sessions: 2 }],
  },
}

const detail: SpendItemDetail = {
  key: 'job:nightshift.planner',
  name: 'nightshift.planner',
  kind: 'routine',
  project: 'nightshift',
  range: '24h',
  bucket_seconds: 3600,
  total_usd: 1.5,
  tokens: 90_000,
  calls: 12,
  timeline: [{ start: '2026-10-18T13:00:00Z', usd: 1 }],
  agents: [
    { key: 'main', name: 'main session', usd: 1.5, tokens: 1, calls: 12 },
  ],
  models: [{ model: 'gpt-6.1-sol', usd: 1.5, tokens: 90_000, calls: 12 }],
  top_calls: [
    {
      at: '2026-10-18T13:10:00Z',
      model: 'gpt-6.1-sol',
      agent: 'main session',
      tokens: 20_000,
      usd: 0.4,
    },
  ],
  runs: { count: 6, cost_per_run: 0.25, median_run: 0.2, per_day: 6 },
}

describe('CostsPage', () => {
  beforeEach(() => {
    nav.reset()
    vi.mocked(fetchSpend).mockResolvedValue(overview)
    vi.mocked(fetchSpendItem).mockResolvedValue(detail)
  })

  it('compares spend with usual and says what usage it could not see', async () => {
    render(<CostsPage />, { wrapper: createQueryClientWrapper() })

    expect(await screen.findByText('$8.40/hr')).toBeInTheDocument()
    expect(screen.getByText(/2\.3× usual/)).toBeInTheDocument()
    expect(screen.getByText('No usual level yet')).toBeInTheDocument()
    expect(
      screen.getByText(
        /Usage captured for 94\.1% of agent work in the last 24 hours; no usage recorded for 2 Codex sessions\. 2 calls used a model with no list price/,
      ),
    ).toBeInTheDocument()
    expect(screen.getByText('Fix the cost page')).toBeInTheDocument()
  })

  it('filters by kind and opens a routine job with its runs', async () => {
    render(<CostsPage />, { wrapper: createQueryClientWrapper() })
    await screen.findByText('nightshift.planner')

    fireEvent.click(screen.getByRole('button', { name: 'Routine' }))
    expect(nav.search).toBe('kind=routine')
    expect(vi.mocked(fetchSpend)).toHaveBeenLastCalledWith(
      '24h',
      { kind: 'routine', project: null, model: null },
      null,
    )

    fireEvent.click(screen.getByRole('button', { name: 'nightshift.planner' }))
    expect(nav.search).toBe('kind=routine&item=job%3Anightshift.planner')
    const drawer = await screen.findByRole('dialog')
    expect(await within(drawer).findByText('Runs')).toBeInTheDocument()
    expect(within(drawer).getByText('$0.25')).toBeInTheDocument()
    expect(vi.mocked(fetchSpendItem)).toHaveBeenCalledWith(
      'job:nightshift.planner',
      '24h',
    )

    fireEvent.keyDown(window, { key: 'Escape' })
    expect(nav.search).toBe('kind=routine')
  })
})
