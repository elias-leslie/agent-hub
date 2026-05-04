'use client'

import type { MutableRefObject } from 'react'
import { useEffect } from 'react'
import type { FeedItem } from './workspace-types'

interface UseWorkspaceViewportOptions {
  autoFollow: boolean
  isAtBottom: boolean
  loading: boolean
  deferredSearch: string
  focusSessionId: string | null
  anchorEntryId: string | null
  latestItemId: string | null
  mergedItems: FeedItem[]
  hydratedEntries: Array<{ status: string; live_status: string | null }>
  messagesLength: number
  status: string
  scrollRef: MutableRefObject<HTMLDivElement | null>
  lastReadItemIdRef: MutableRefObject<string | null>
  initialViewportSettledRef: MutableRefObject<boolean>
  scrollToBottom: (behavior?: ScrollBehavior) => void
  clearInitialViewportTimeout: () => void
  markLatestAsRead: (itemId?: string | null) => void
  setIsAtBottom: (value: boolean) => void
  setFirstUnreadItemId: (
    updater: (current: string | null) => string | null,
  ) => void
}

export function useWorkspaceViewport({
  autoFollow,
  isAtBottom,
  loading,
  deferredSearch,
  focusSessionId,
  anchorEntryId,
  latestItemId,
  mergedItems,
  hydratedEntries,
  messagesLength,
  status,
  scrollRef,
  lastReadItemIdRef,
  initialViewportSettledRef,
  scrollToBottom,
  clearInitialViewportTimeout,
  markLatestAsRead,
  setIsAtBottom,
  setFirstUnreadItemId,
}: UseWorkspaceViewportOptions) {
  // Auto-follow: scroll to bottom when new messages arrive
  useEffect(() => {
    const container = scrollRef.current
    if (!container || !autoFollow) return
    scrollToBottom('smooth')
    setIsAtBottom(true)
    markLatestAsRead()
  }, [messagesLength, status, autoFollow])

  // Initial viewport settle: scroll to bottom on first load
  useEffect(() => {
    if (initialViewportSettledRef.current || loading || !autoFollow) return
    if (deferredSearch.trim() || focusSessionId || anchorEntryId) return
    if (hydratedEntries.length === 0 && messagesLength === 0) return
    initialViewportSettledRef.current = true
    clearInitialViewportTimeout()
    const timeout = window.setTimeout(() => {
      requestAnimationFrame(() => {
        scrollToBottom('auto')
        setIsAtBottom(true)
        markLatestAsRead()
      })
    }, 0)
    return () => {
      window.clearTimeout(timeout)
      clearInitialViewportTimeout()
    }
  }, [
    anchorEntryId,
    autoFollow,
    clearInitialViewportTimeout,
    deferredSearch,
    focusSessionId,
    hydratedEntries.length,
    loading,
    messagesLength,
  ])

  // Track unread items when new activity arrives
  useEffect(() => {
    if (!latestItemId) return
    if (!lastReadItemIdRef.current) {
      lastReadItemIdRef.current = latestItemId
      return
    }
    if (latestItemId === lastReadItemIdRef.current) return
    if (autoFollow && isAtBottom) {
      markLatestAsRead(latestItemId)
      return
    }
    const previousIndex = mergedItems.findIndex(
      (item) => item.id === lastReadItemIdRef.current,
    )
    const nextUnreadId =
      mergedItems[Math.max(previousIndex + 1, 0)]?.id ?? latestItemId
    setFirstUnreadItemId((current) => current ?? nextUnreadId)
  }, [latestItemId, mergedItems, autoFollow, isAtBottom])

  // Follow live work as it updates
  useEffect(() => {
    if (!autoFollow) return
    const hasLiveWork = hydratedEntries.some(
      (entry) => entry.status === 'active' || entry.live_status === 'active',
    )
    if (!hasLiveWork) return
    const container = scrollRef.current
    if (!container) return
    scrollToBottom('smooth')
    setIsAtBottom(true)
    markLatestAsRead()
  }, [autoFollow, hydratedEntries])
}
