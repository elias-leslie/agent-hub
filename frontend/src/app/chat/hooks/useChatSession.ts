import { useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useRef, useState } from 'react'

const LEGACY_STORAGE_KEY = 'persona_active_session_id'
const CONTEXT_STORAGE_KEY = 'agent_hub_active_session_by_context'

interface UseChatSessionOptions {
  contextKey?: string | null
}

function readContextSessions(): Record<string, string> {
  if (typeof window === 'undefined') return {}
  const raw = localStorage.getItem(CONTEXT_STORAGE_KEY)
  if (!raw) return {}
  try {
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed))
      return {}
    return Object.fromEntries(
      Object.entries(parsed).filter(
        (entry): entry is [string, string] =>
          typeof entry[0] === 'string' &&
          typeof entry[1] === 'string' &&
          entry[1].length > 0,
      ),
    )
  } catch {
    return {}
  }
}

function getStoredSessionId(contextKey?: string | null): string | null {
  if (typeof window === 'undefined') return null
  if (contextKey) return readContextSessions()[contextKey] ?? null
  return localStorage.getItem(LEGACY_STORAGE_KEY)
}

function storeSessionId(
  sessionId: string | null,
  contextKey?: string | null,
): void {
  if (typeof window === 'undefined') return
  if (contextKey) {
    const sessions = readContextSessions()
    if (sessionId) {
      sessions[contextKey] = sessionId
    } else {
      delete sessions[contextKey]
    }
    if (Object.keys(sessions).length > 0) {
      localStorage.setItem(CONTEXT_STORAGE_KEY, JSON.stringify(sessions))
    } else {
      localStorage.removeItem(CONTEXT_STORAGE_KEY)
    }
    return
  }

  if (sessionId) {
    localStorage.setItem(LEGACY_STORAGE_KEY, sessionId)
  } else {
    localStorage.removeItem(LEGACY_STORAGE_KEY)
  }
}

function clearSessionIdFromUrl(): void {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  url.searchParams.delete('session_id')
  window.history.replaceState(null, '', url.toString())
}

function setSessionIdInUrl(sessionId: string): void {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  url.searchParams.set('session_id', sessionId)
  window.history.replaceState(null, '', url.toString())
}

function pushSessionIdInUrl(
  router: { push: (href: string, options?: { scroll?: boolean }) => void },
  sessionId: string | null,
): void {
  if (typeof window === 'undefined') return
  const url = new URL(window.location.href)
  if (sessionId) {
    url.searchParams.set('session_id', sessionId)
  } else {
    url.searchParams.delete('session_id')
  }
  router.push(url.pathname + url.search, { scroll: false })
}

interface UseChatSessionReturn {
  activeSessionId: string | null
  sidebarRefreshTrigger: number
  sessionError: string | null
  setSessionError: (error: string | null) => void
  handleSessionCreated: (newSessionId: string) => void
  handleSelectSession: (sessionId: string | null) => void
  handleContextChange: () => void
  handleNewSession: () => void
}

export function useChatSession(
  options: UseChatSessionOptions = {},
): UseChatSessionReturn {
  const router = useRouter()
  const searchParams = useSearchParams()
  const sessionIdFromUrl = searchParams.get('session_id')
  const contextKey = options.contextKey ?? null
  const ignoreUrlOnNextContextLoad = useRef(false)

  // Priority: URL param > localStorage
  const [activeSessionId, setActiveSessionId] = useState<string | null>(
    sessionIdFromUrl || getStoredSessionId(contextKey),
  )
  const [sidebarRefreshTrigger, setSidebarRefreshTrigger] = useState(0)
  const [sessionError, setSessionError] = useState<string | null>(null)

  useEffect(() => {
    if (!contextKey) return
    const shouldIgnoreUrl = ignoreUrlOnNextContextLoad.current
    ignoreUrlOnNextContextLoad.current = false
    const nextSessionId = shouldIgnoreUrl
      ? getStoredSessionId(contextKey)
      : sessionIdFromUrl || getStoredSessionId(contextKey)
    setActiveSessionId(nextSessionId)
    setSessionError(null)
  }, [contextKey, sessionIdFromUrl])

  const handleSessionCreated = useCallback(
    (newSessionId: string) => {
      setActiveSessionId(newSessionId)
      storeSessionId(newSessionId, contextKey)
      // Update URL for bookmarking using replaceState instead of router.push
      // to avoid triggering Next.js Suspense re-render, which would remount
      // ChatContent and reinitialize activeSessionId from the URL, wiping
      // in-flight streaming messages.
      setSessionIdInUrl(newSessionId)
      setSidebarRefreshTrigger((prev) => prev + 1)
    },
    [contextKey],
  )

  const handleSelectSession = useCallback(
    (sessionId: string | null) => {
      setActiveSessionId(sessionId)
      storeSessionId(sessionId, contextKey)
      setSessionError(null)
      pushSessionIdInUrl(router, sessionId)
    },
    [contextKey, router],
  )

  const handleContextChange = useCallback(() => {
    ignoreUrlOnNextContextLoad.current = true
    setActiveSessionId(null)
    setSessionError(null)
    clearSessionIdFromUrl()
  }, [])

  const handleNewSession = useCallback(() => {
    // Clear the session in place via replaceState (NOT router.push). A push
    // remounts the Suspense tree on the /chat page, which resets selectedAgent
    // and falls back to the default agent (persona/Jenny). replaceState drops
    // session_id from the URL while preserving the current agent selection.
    setActiveSessionId(null)
    storeSessionId(null, contextKey)
    setSessionError(null)
    clearSessionIdFromUrl()
  }, [contextKey])

  return {
    activeSessionId,
    sidebarRefreshTrigger,
    sessionError,
    setSessionError,
    handleSessionCreated,
    handleSelectSession,
    handleContextChange,
    handleNewSession,
  }
}
