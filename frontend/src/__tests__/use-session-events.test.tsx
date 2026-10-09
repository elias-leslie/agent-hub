import { act, renderHook } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { useSessionEvents } from '@/hooks/use-session-events'

class FakeSocket {
  static OPEN = 1
  static instances: FakeSocket[] = []
  readyState = 0
  sent: string[] = []
  onopen: (() => void) | null = null
  onmessage: ((event: { data: string }) => void) | null = null
  onerror: (() => void) | null = null
  onclose: (() => void) | null = null

  constructor() {
    FakeSocket.instances.push(this)
  }

  send(data: string) {
    this.sent.push(data)
  }

  // Real sockets fire onclose asynchronously; tests trigger it explicitly.
  close() {
    this.readyState = 3
  }

  open() {
    this.readyState = FakeSocket.OPEN
    this.onopen?.()
  }

  receive(payload: unknown) {
    this.onmessage?.({ data: JSON.stringify(payload) })
  }
}

describe('useSessionEvents', () => {
  beforeEach(() => {
    FakeSocket.instances = []
    vi.stubGlobal('WebSocket', FakeSocket)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('does not resend filter updates for re-renders with equal filters', () => {
    const { rerender } = renderHook(() => useSessionEvents())
    const socket = FakeSocket.instances[0]
    act(() => {
      socket.open()
      socket.receive({ type: 'subscribed', subscription_id: 'sub-1' })
    })
    for (let i = 0; i < 5; i += 1) {
      act(() => {
        socket.receive({ event_type: 'message', session_id: 's', data: {} })
      })
      rerender()
    }

    const updates = socket.sent.filter((m) => JSON.parse(m).type === 'update')
    expect(updates.length).toBeLessThanOrEqual(1)
  })

  it('ignores close events from a replaced socket', () => {
    vi.useFakeTimers()
    const { result } = renderHook(() => useSessionEvents())
    const first = FakeSocket.instances[0]
    act(() => {
      first.open()
      result.current.connect()
    })
    const current = FakeSocket.instances.at(-1)
    expect(current).not.toBe(first)
    const countBefore = FakeSocket.instances.length

    act(() => {
      current?.open()
      first.onclose?.()
      vi.advanceTimersByTime(60_000)
    })

    expect(FakeSocket.instances.length).toBe(countBefore)
    expect(result.current.status).toBe('connected')
    vi.useRealTimers()
  })
})
