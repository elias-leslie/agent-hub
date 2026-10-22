import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSessionEfficiency, fetchSessionHotspots } from '@/lib/api/admin'
import { fetchApi } from '@/lib/api-config'
import { activityFixture } from './activity-cost-fixture'

vi.mock('@/lib/api-config', () => ({
  fetchApi: vi.fn(),
  getApiBaseUrl: () => '',
}))

beforeEach(() => vi.resetAllMocks())

describe('session hotspot activity contract', () => {
  it('forwards the shared scope to efficiency charts and rejects an interval mismatch', async () => {
    vi.mocked(fetchApi).mockResolvedValue(
      new Response(JSON.stringify(activityFixture)),
    )
    const scope = {
      accounting_start: activityFixture.window_start,
      accounting_end: activityFixture.window_end,
      work_role: 'unknown',
      harness: 'pi',
      kind: ['coding'] as const,
      roots_only: true,
    }
    expect(await fetchSessionEfficiency(scope)).toEqual(activityFixture)
    const path = vi.mocked(fetchApi).mock.calls[0][0]
    const query = new URL(String(path), 'https://example.test').searchParams
    expect(query.get('accounting_start')).toBe(scope.accounting_start)
    expect(query.get('accounting_end')).toBe(scope.accounting_end)
    expect(query.get('work_role')).toBe('unknown')
    expect(query.get('harness')).toBe('pi')
    expect(query.get('kind')).toBe('coding')
    vi.mocked(fetchApi).mockResolvedValue(
      new Response(JSON.stringify(activityFixture)),
    )
    await expect(
      fetchSessionEfficiency({
        ...scope,
        accounting_start: '2026-10-20T12:00:00Z',
      }),
    ).rejects.toThrow('different accounting interval')
  })

  it('keeps the existing endpoint and validates activity at its boundary', async () => {
    vi.mocked(fetchApi).mockResolvedValue(
      new Response(JSON.stringify({ activity_cost: activityFixture })),
    )
    expect((await fetchSessionHotspots()).activity_cost).toEqual(
      activityFixture,
    )
    expect(fetchApi).toHaveBeenCalledWith(
      '/api/admin/session-hotspots?hours=24&limit=5',
    )
    vi.mocked(fetchApi).mockResolvedValue(
      new Response(JSON.stringify({ activity_cost: { sessions: 0 } })),
    )
    await expect(fetchSessionHotspots()).rejects.toThrow(
      'incomplete or invalid',
    )
  })

  it('distinguishes absent data from a failed request', async () => {
    vi.mocked(fetchApi).mockResolvedValue(new Response('{}'))
    expect((await fetchSessionHotspots()).activity_cost).toBeNull()
    vi.mocked(fetchApi).mockResolvedValue(new Response('{}', { status: 403 }))
    await expect(fetchSessionHotspots()).rejects.toThrow('(403)')
  })
})
