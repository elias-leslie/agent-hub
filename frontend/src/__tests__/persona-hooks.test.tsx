import { act, fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { usePersona } from '@/app/persona/hooks/usePersona'

vi.mock('@/lib/api-config', () => ({
  buildApiUrl: (path: string) => path,
  fetchApi: vi.fn(),
}))

vi.mock('@/components/error/toast', () => ({
  useToastActions: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  }),
}))

import { fetchApi } from '@/lib/api-config'

function jsonResponse(data: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: vi.fn().mockResolvedValue(data),
  } as unknown as Response
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

function PersonaHarness() {
  const { persona, updatePersona, autosave } = usePersona()

  return (
    <div>
      <div data-testid="persona-name">{persona?.name ?? ''}</div>
      <div data-testid="autosave-status">{autosave.status}</div>
      <button onClick={() => updatePersona({ name: 'Alpha' })}>Alpha</button>
      <button onClick={() => updatePersona({ name: 'Beta' })}>Beta</button>
    </div>
  )
}

describe('usePersona', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('ignores stale autosave responses that resolve after a newer save', async () => {
    const firstSave = deferred<Response>()
    const secondSave = deferred<Response>()

    vi.mocked(fetchApi)
      .mockResolvedValueOnce(jsonResponse({ name: 'Persona' }))
      .mockReturnValueOnce(firstSave.promise)
      .mockReturnValueOnce(secondSave.promise)

    render(<PersonaHarness />)

    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByTestId('persona-name')).toHaveTextContent('Persona')

    fireEvent.click(screen.getByText('Alpha'))
    expect(screen.getByTestId('autosave-status')).toHaveTextContent('scheduled')
    await act(async () => {
      vi.advanceTimersByTime(500)
    })
    expect(screen.getByTestId('autosave-status')).toHaveTextContent('saving')

    fireEvent.click(screen.getByText('Beta'))
    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    await act(async () => {
      secondSave.resolve(jsonResponse({ name: 'Beta' }))
      await Promise.resolve()
    })

    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByTestId('persona-name')).toHaveTextContent('Beta')
    expect(screen.getByTestId('autosave-status')).toHaveTextContent('saved')

    await act(async () => {
      firstSave.resolve(jsonResponse({ name: 'Alpha' }))
      await Promise.resolve()
    })

    expect(screen.getByTestId('persona-name')).toHaveTextContent('Beta')
  })

  it('cancels a pending autosave when the component unmounts', async () => {
    vi.mocked(fetchApi).mockResolvedValueOnce(jsonResponse({ name: 'Persona' }))

    const { unmount } = render(<PersonaHarness />)

    await act(async () => {
      await Promise.resolve()
    })
    expect(screen.getByTestId('persona-name')).toHaveTextContent('Persona')

    fireEvent.click(screen.getByText('Alpha'))
    unmount()

    await act(async () => {
      vi.advanceTimersByTime(500)
    })

    expect(fetchApi).toHaveBeenCalledTimes(1)
  })

  it('surfaces autosave errors after a failed save', async () => {
    vi.mocked(fetchApi)
      .mockResolvedValueOnce(jsonResponse({ name: 'Persona' }))
      .mockResolvedValueOnce(jsonResponse({ detail: 'bad' }, 500))

    render(<PersonaHarness />)

    await act(async () => {
      await Promise.resolve()
    })

    fireEvent.click(screen.getByText('Alpha'))

    await act(async () => {
      vi.advanceTimersByTime(500)
      await Promise.resolve()
    })

    expect(screen.getByTestId('autosave-status')).toHaveTextContent('error')
  })
})
