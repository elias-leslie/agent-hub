import { useCallback, useState } from 'react'
import type { SessionListItem } from '@/lib/api'

interface UseSessionKeyboardProps {
  sessions: SessionListItem[]
  onToggleExpand: (sessionId: string) => void
  onClearExpansion: () => void
}

export function useSessionKeyboard({
  sessions,
  onToggleExpand,
  onClearExpansion,
}: UseSessionKeyboardProps) {
  const [focusedRowIndex, setFocusedRowIndex] = useState<number>(-1)

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (!sessions.length) return

      switch (e.key) {
        case 'ArrowDown':
          e.preventDefault()
          setFocusedRowIndex((prev) => Math.min(prev + 1, sessions.length - 1))
          break
        case 'ArrowUp':
          e.preventDefault()
          setFocusedRowIndex((prev) => Math.max(prev - 1, 0))
          break
        case 'Enter':
        case ' ':
          e.preventDefault()
          if (focusedRowIndex >= 0 && focusedRowIndex < sessions.length) {
            onToggleExpand(sessions[focusedRowIndex].id)
          }
          break
        case 'Escape':
          e.preventDefault()
          onClearExpansion()
          break
      }
    },
    [sessions, focusedRowIndex, onToggleExpand, onClearExpansion],
  )

  return {
    focusedRowIndex,
    handleKeyDown,
  }
}
