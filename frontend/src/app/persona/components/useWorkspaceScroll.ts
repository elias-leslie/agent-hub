'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { PROGRAMMATIC_SCROLL_GRACE_MS } from './workspace-types'
import { isNearBottom } from './workspace-utils'

interface UseWorkspaceScrollOptions {
  latestItemId: string | null
  loading: boolean
}

export function useWorkspaceScroll({
  latestItemId,
  loading,
}: UseWorkspaceScrollOptions) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const autoFollowRef = useRef(true)
  const initialViewportTimeoutRef = useRef<number | null>(null)
  const programmaticScrollUntilRef = useRef(0)
  const initialViewportSettledRef = useRef(false)
  const olderHistoryAnchorRef = useRef<{
    scrollHeight: number
    scrollTop: number
  } | null>(null)
  const lastReadItemIdRef = useRef<string | null>(null)

  const [autoFollow, setAutoFollow] = useState(true)
  const [isAtBottom, setIsAtBottom] = useState(true)
  const [firstUnreadItemId, setFirstUnreadItemId] = useState<string | null>(
    null,
  )

  useEffect(() => {
    autoFollowRef.current = autoFollow
  }, [autoFollow])

  const scrollToBottom = useCallback((behavior: ScrollBehavior = 'smooth') => {
    const container = scrollRef.current
    if (!container || typeof container.scrollTo !== 'function') return
    programmaticScrollUntilRef.current =
      Date.now() + PROGRAMMATIC_SCROLL_GRACE_MS
    container.scrollTo({ top: container.scrollHeight, behavior })
  }, [])

  const clearInitialViewportTimeout = useCallback(() => {
    if (initialViewportTimeoutRef.current == null) return
    window.clearTimeout(initialViewportTimeoutRef.current)
    initialViewportTimeoutRef.current = null
  }, [])

  const markLatestAsRead = useCallback(
    (itemId: string | null = latestItemId) => {
      if (!itemId) return
      lastReadItemIdRef.current = itemId
      setFirstUnreadItemId(null)
    },
    [latestItemId],
  )

  const captureScrollAnchor = useCallback(() => {
    const container = scrollRef.current
    if (!container) return
    olderHistoryAnchorRef.current = {
      scrollHeight: container.scrollHeight,
      scrollTop: container.scrollTop,
    }
  }, [])

  useEffect(() => {
    const container = scrollRef.current
    if (!container) return
    const handleScroll = () => {
      const nearBottom = isNearBottom(container)
      setIsAtBottom(nearBottom)
      if (Date.now() < programmaticScrollUntilRef.current) return
      if (nearBottom) {
        if (!autoFollowRef.current) setAutoFollow(true)
        if (latestItemId) {
          lastReadItemIdRef.current = latestItemId
          setFirstUnreadItemId(null)
        }
        return
      }
      if (autoFollowRef.current) {
        clearInitialViewportTimeout()
        setAutoFollow(false)
      }
    }
    container.addEventListener('scroll', handleScroll, { passive: true })
    return () => container.removeEventListener('scroll', handleScroll)
  }, [clearInitialViewportTimeout, latestItemId])

  useEffect(() => {
    const container = scrollRef.current
    const anchor = olderHistoryAnchorRef.current
    if (!container || !anchor || loading) return
    const heightDelta = container.scrollHeight - anchor.scrollHeight
    container.scrollTop = anchor.scrollTop + Math.max(heightDelta, 0)
    olderHistoryAnchorRef.current = null
  }, [loading])

  return {
    scrollRef,
    autoFollow,
    setAutoFollow,
    isAtBottom,
    setIsAtBottom,
    firstUnreadItemId,
    setFirstUnreadItemId,
    lastReadItemIdRef,
    initialViewportSettledRef,
    autoFollowRef,
    scrollToBottom,
    clearInitialViewportTimeout,
    markLatestAsRead,
    captureScrollAnchor,
  }
}
