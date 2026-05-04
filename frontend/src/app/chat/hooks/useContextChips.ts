import { useCallback, useState } from 'react'

export interface ContextChip {
  id: string
  type: 'file' | 'folder' | 'url'
  label: string
  value: string
}

interface UseContextChipsReturn {
  contextChips: ContextChip[]
  addContextChip: (type: ContextChip['type'], value: string) => void
  removeContextChip: (id: string) => void
}

export function useContextChips(): UseContextChipsReturn {
  const [contextChips, setContextChips] = useState<ContextChip[]>([])

  const addContextChip = useCallback(
    (type: ContextChip['type'], value: string) => {
      const label = value.split('/').pop() || value
      const id = `${type}-${Date.now()}`
      setContextChips((prev) => [...prev, { id, type, label, value }])
    },
    [],
  )

  const removeContextChip = useCallback((id: string) => {
    setContextChips((prev) => prev.filter((c) => c.id !== id))
  }, [])

  return {
    contextChips,
    addContextChip,
    removeContextChip,
  }
}
