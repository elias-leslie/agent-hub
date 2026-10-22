import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSessionHotspots } from '@/lib/api/admin'
import { fetchApi } from '@/lib/api-config'
import { activityFixture } from './activity-cost-fixture'

vi.mock('@/lib/api-config', () => ({ fetchApi: vi.fn() }))

beforeEach(() => vi.resetAllMocks())

describe('session hotspot activity contract', () => {
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
