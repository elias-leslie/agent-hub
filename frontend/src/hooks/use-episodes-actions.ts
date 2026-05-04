'use client'

import { useCallback, useState } from 'react'
import { bulkTag } from '@/lib/api/memory-tags'
import type { MemoryCategory } from '@/lib/memory-api'
import { batchUpdateTier } from '@/lib/memory-api'

interface UseEpisodesActionsProps {
  deleteOne: (id: string) => Promise<void>
  deleteSelected: () => Promise<void>
  refresh: () => void
  isDeleting: boolean
}

export function useEpisodesActions({
  deleteOne,
  deleteSelected,
  refresh,
  isDeleting,
}: UseEpisodesActionsProps) {
  const [showDeleteModal, setShowDeleteModal] = useState(false)
  const [pendingDeleteId, setPendingDeleteId] = useState<string | null>(null)
  const [expandedMemoryId, setExpandedMemoryId] = useState<string | null>(null)

  const handleDeleteClick = useCallback((id: string) => {
    setPendingDeleteId(id)
    setShowDeleteModal(true)
  }, [])

  const handleBulkDeleteClick = useCallback(() => {
    setPendingDeleteId(null)
    setShowDeleteModal(true)
  }, [])

  const handleBulkTierChange = useCallback(
    async (ids: string[], tier: MemoryCategory) => {
      await batchUpdateTier(ids, tier)
      refresh()
    },
    [refresh],
  )

  const handleBulkTag = useCallback(
    async (ids: string[], addTags: string[], removeTags: string[]) => {
      await bulkTag(ids, addTags, removeTags)
      refresh()
    },
    [refresh],
  )

  const handleConfirmDelete = useCallback(async () => {
    if (pendingDeleteId) {
      await deleteOne(pendingDeleteId)
      if (expandedMemoryId === pendingDeleteId) {
        setExpandedMemoryId(null)
      }
    } else {
      await deleteSelected()
      setExpandedMemoryId(null)
    }
    setShowDeleteModal(false)
    setPendingDeleteId(null)
  }, [pendingDeleteId, deleteOne, deleteSelected, expandedMemoryId])

  const handleToggleExpand = useCallback((id: string) => {
    setExpandedMemoryId((prev) => (prev === id ? null : id))
  }, [])

  const closeDeleteModal = useCallback(() => {
    setShowDeleteModal(false)
    setPendingDeleteId(null)
  }, [])

  return {
    showDeleteModal,
    pendingDeleteId,
    expandedMemoryId,
    handleDeleteClick,
    handleBulkDeleteClick,
    handleBulkTierChange,
    handleBulkTag,
    handleConfirmDelete,
    handleToggleExpand,
    closeDeleteModal,
    isDeleting,
  }
}
