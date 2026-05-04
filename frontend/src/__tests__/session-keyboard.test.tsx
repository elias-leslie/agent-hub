import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { useSessionKeyboard } from '@/app/sessions/hooks/useSessionKeyboard'

describe('useSessionKeyboard', () => {
  it('supports Arrow navigation plus Enter/Space expand and Escape collapse', () => {
    const onToggleExpand = vi.fn()
    const onClearExpansion = vi.fn()
    const sessions = [{ id: 'sess-1' }, { id: 'sess-2' }] as never[]

    const { result } = renderHook(() =>
      useSessionKeyboard({
        sessions,
        onToggleExpand,
        onClearExpansion,
      }),
    )

    const keyEvent = (key: string) =>
      ({
        key,
        preventDefault: vi.fn(),
      }) as never

    act(() => {
      result.current.handleKeyDown(keyEvent('ArrowDown'))
    })
    expect(result.current.focusedRowIndex).toBe(0)

    act(() => {
      result.current.handleKeyDown(keyEvent('Enter'))
    })
    expect(onToggleExpand).toHaveBeenCalledWith('sess-1')

    act(() => {
      result.current.handleKeyDown(keyEvent(' '))
    })
    expect(onToggleExpand).toHaveBeenLastCalledWith('sess-1')

    act(() => {
      result.current.handleKeyDown(keyEvent('Escape'))
    })
    expect(onClearExpansion).toHaveBeenCalledTimes(1)
  })
})
