import { renderHook } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it } from 'vitest'
import { ToastProvider, useToastActions } from '@/components/error/toast'

describe('useToastActions', () => {
  it('returns the same actions object across renders', () => {
    const wrapper = ({ children }: { children: ReactNode }) => (
      <ToastProvider>{children}</ToastProvider>
    )
    const { result, rerender } = renderHook(() => useToastActions(), {
      wrapper,
    })
    const first = result.current
    rerender()
    expect(result.current).toBe(first)
  })
})
