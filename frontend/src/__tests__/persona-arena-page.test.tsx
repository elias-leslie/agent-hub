import { describe, expect, it, vi } from 'vitest'

const mockRedirect = vi.fn()
vi.mock('next/navigation', () => ({
  redirect: (url: string) => {
    mockRedirect(url)
  },
}))

describe('PersonaArenaPage redirect', () => {
  it('redirects /persona/arena to /arena/persona', async () => {
    const { default: PersonaArenaRedirect } = await import(
      '@/app/persona/arena/page'
    )

    PersonaArenaRedirect()

    expect(mockRedirect).toHaveBeenCalledWith('/arena/persona')
  })
})
