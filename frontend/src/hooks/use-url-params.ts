'use client'

import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback } from 'react'
import type { MemoryCategory, MemoryScope } from '@/lib/memory-api'

export function useUrlParams() {
  const router = useRouter()
  const searchParams = useSearchParams()

  const updateParams = useCallback(
    (updates: Record<string, string | undefined>) => {
      const params = new URLSearchParams(searchParams.toString())
      Object.entries(updates).forEach(([key, value]) => {
        if (value === undefined) {
          params.delete(key)
        } else {
          params.set(key, value)
        }
      })
      router.push(`/memory?${params.toString()}`, { scroll: false })
    },
    [router, searchParams],
  )

  const handleScopeChange = useCallback(
    (newScope: MemoryScope | undefined) => updateParams({ scope: newScope }),
    [updateParams],
  )

  const handleCategoryChange = useCallback(
    (newCategory: MemoryCategory | undefined) =>
      updateParams({ category: newCategory }),
    [updateParams],
  )

  return {
    handleScopeChange,
    handleCategoryChange,
  }
}
