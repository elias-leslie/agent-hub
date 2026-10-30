import { beforeEach, describe, expect, it, vi } from 'vitest'
import { fetchSession } from '@/lib/api/sessions'
import { fetchApi } from '@/lib/api-config'

vi.mock('@/lib/api-config', () => ({
  fetchApi: vi.fn(),
  getApiBaseUrl: () => '',
}))

beforeEach(() => vi.resetAllMocks())

describe('fetchSession', () => {
  // The server's default is the summary only, so every read says which it wants.
  it.each([true, false])('sends include_events=%s', async (includeEvents) => {
    vi.mocked(fetchApi).mockResolvedValue(
      new Response(JSON.stringify({ id: 's1' })),
    )
    await fetchSession('s1', { includeEvents })
    const path = String(vi.mocked(fetchApi).mock.calls[0][0])
    expect(
      new URL(path, 'https://example.test').searchParams.get('include_events'),
    ).toBe(String(includeEvents))
  })
})
