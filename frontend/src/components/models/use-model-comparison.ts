'use client'

import { useCallback, useEffect, useState } from 'react'
import type { ModelOption } from '@/hooks/use-models-catalog'

/** Most models the comparison panel shows side by side. */
export const MAX_COMPARED_MODELS = 3

/**
 * Selection for the model comparison panel. Selecting cards only builds the
 * set; the panel opens when the caller asks for it and closes when the set
 * empties.
 */
export function useModelComparison() {
  const [selectedModels, setSelectedModels] = useState<ModelOption[]>([])
  const [isOpen, setIsOpen] = useState(false)

  const toggleModel = useCallback((model: ModelOption) => {
    setSelectedModels((prev) => {
      if (prev.some((m) => m.id === model.id)) {
        return prev.filter((m) => m.id !== model.id)
      }
      if (prev.length >= MAX_COMPARED_MODELS) return prev
      return [...prev, model]
    })
  }, [])

  const removeModel = useCallback((modelId: string) => {
    setSelectedModels((prev) => prev.filter((m) => m.id !== modelId))
  }, [])

  // An emptied selection closes the panel so the next pick does not reopen it.
  useEffect(() => {
    if (selectedModels.length === 0) setIsOpen(false)
  }, [selectedModels.length])

  const open = useCallback(() => setIsOpen(true), [])
  const close = useCallback(() => setIsOpen(false), [])

  return {
    selectedModels,
    isSelected: (modelId: string) =>
      selectedModels.some((m) => m.id === modelId),
    isOpen: isOpen && selectedModels.length > 0,
    toggleModel,
    removeModel,
    open,
    close,
  }
}
