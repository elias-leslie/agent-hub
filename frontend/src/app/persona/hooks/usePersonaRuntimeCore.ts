'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'

import { useSessionEvents } from '@/hooks/use-session-events'
import {
  cancelSessionStream,
  fetchSession,
  fetchSessions,
  type Session,
  type SessionListItem,
} from '@/lib/api/sessions'
import type { SessionEvent } from '@/types/events'

const IDLE_POLL_MS = 15_000
const ACTIVE_POLL_MS = 5_000

function sortSessionsByUpdatedAt(
  sessions: SessionListItem[],
): SessionListItem[] {
  return [...sessions].sort(
    (a, b) => +new Date(b.updated_at) - +new Date(a.updated_at),
  )
}

function isRuntimeActive(
  session: Pick<SessionListItem, 'status' | 'live_activity'>,
): boolean {
  return (
    session.status === 'active' ||
    session.live_activity?.status === 'active' ||
    session.live_activity?.phase === 'waiting_for_model' ||
    session.live_activity?.phase === 'running_tool' ||
    session.live_activity?.phase === 'finalizing'
  )
}

function upsertSessionListItem(
  sessions: SessionListItem[],
  session: SessionListItem,
): SessionListItem[] {
  return sortSessionsByUpdatedAt([
    session,
    ...sessions.filter((entry) => entry.id !== session.id),
  ])
}

export function toSessionListItem(session: Session): SessionListItem {
  const sessionRecord = session as Session &
    Partial<
      Pick<
        SessionListItem,
        'parent_session_id' | 'external_id' | 'current_branch'
      >
    >
  return {
    id: session.id,
    project_id: session.project_id,
    provider: session.provider,
    model: session.model,
    requested_provider: session.requested_provider ?? null,
    requested_model: session.requested_model ?? null,
    effective_provider: session.effective_provider ?? null,
    effective_model: session.effective_model ?? null,
    requested_model_display_name: session.requested_model_display_name ?? null,
    effective_model_display_name: session.effective_model_display_name ?? null,
    fallback_used: session.fallback_used ?? false,
    fallback_reason: session.fallback_reason ?? null,
    status: session.status,
    agent_slug: session.agent_slug ?? null,
    session_type: session.session_type,
    parent_session_id: sessionRecord.parent_session_id ?? null,
    external_id: sessionRecord.external_id ?? null,
    client_id: session.client_id ?? null,
    request_source: session.request_source ?? null,
    source_client: session.source_client ?? null,
    source_path: session.source_path ?? null,
    attribution_kind: session.attribution_kind ?? null,
    attribution_label: session.attribution_label ?? null,
    attribution_detail: session.attribution_detail ?? null,
    current_branch: sessionRecord.current_branch ?? null,
    live_activity: session.live_activity ?? null,
    message_count: session.message_count ?? session.messages?.length ?? 0,
    event_count: session.event_count ?? null,
    total_input_tokens: session.total_input_tokens ?? 0,
    total_output_tokens: session.total_output_tokens ?? 0,
    created_at: session.created_at,
    updated_at: session.updated_at,
  }
}

function truncateText(value: string, maxLength = 96): string {
  if (value.length <= maxLength) {
    return value
  }
  return `${value.slice(0, maxLength - 1)}…`
}

function patchSessionWithLiveEvent(
  session: SessionListItem,
  event: SessionEvent,
): SessionListItem {
  const liveActivity = { ...(session.live_activity ?? {}) }
  liveActivity.last_event_at = event.timestamp
  liveActivity.last_model_activity_at = event.timestamp

  if (event.event_type === 'message') {
    const content =
      typeof event.data === 'object' &&
      event.data &&
      'content' in event.data &&
      typeof event.data.content === 'string'
        ? event.data.content
        : null
    const role =
      typeof event.data === 'object' &&
      event.data &&
      'role' in event.data &&
      typeof event.data.role === 'string'
        ? event.data.role
        : null
    liveActivity.phase =
      role === 'assistant' ? 'finalizing' : 'waiting_for_model'
    liveActivity.status = 'active'
    liveActivity.summary = content ? truncateText(content) : 'New message'
    liveActivity.last_event_type = role ? `${role}_message` : 'message'
  } else if (event.event_type === 'tool_use') {
    const toolName =
      typeof event.data === 'object' &&
      event.data &&
      'tool_name' in event.data &&
      typeof event.data.tool_name === 'string'
        ? event.data.tool_name
        : 'tool'
    liveActivity.phase = 'running_tool'
    liveActivity.status = 'active'
    liveActivity.summary = `Running ${toolName}`
    liveActivity.current_tool_name = toolName
    liveActivity.last_tool_name = toolName
    liveActivity.last_tool_started_at = event.timestamp
    liveActivity.last_event_type = 'tool_use'
  } else if (event.event_type === 'tool_result') {
    const toolName =
      typeof event.data === 'object' &&
      event.data &&
      'tool_name' in event.data &&
      typeof event.data.tool_name === 'string'
        ? event.data.tool_name
        : liveActivity.last_tool_name
    const toolOutput =
      typeof event.data === 'object' &&
      event.data &&
      'tool_output' in event.data &&
      typeof event.data.tool_output === 'object'
        ? event.data.tool_output
        : null
    const resultContent =
      toolOutput &&
      'content' in toolOutput &&
      typeof toolOutput.content === 'string'
        ? toolOutput.content
        : null
    const isError =
      typeof event.data === 'object' &&
      event.data &&
      'is_error' in event.data &&
      typeof event.data.is_error === 'boolean'
        ? event.data.is_error
        : toolOutput &&
            'is_error' in toolOutput &&
            typeof toolOutput.is_error === 'boolean'
          ? toolOutput.is_error
          : false
    liveActivity.phase = 'waiting_for_model'
    liveActivity.status = 'active'
    liveActivity.summary = isError
      ? `Tool failed: ${toolName || 'tool'}`
      : resultContent
        ? truncateText(resultContent)
        : `Waiting for model after ${toolName || 'tool'}`
    liveActivity.current_tool_name = null
    liveActivity.last_tool_name = toolName ?? null
    liveActivity.last_tool_finished_at = event.timestamp
    liveActivity.last_tool_error = isError
    liveActivity.last_event_type = 'tool_result'
  } else if (event.event_type === 'complete') {
    liveActivity.phase = 'completed'
    liveActivity.status = 'completed'
    liveActivity.summary = 'Execution completed'
    liveActivity.current_tool_name = null
    liveActivity.last_event_type = 'complete'
  } else if (event.event_type === 'error') {
    const errorMessage =
      typeof event.data === 'object' &&
      event.data &&
      'error_message' in event.data &&
      typeof event.data.error_message === 'string'
        ? event.data.error_message
        : 'Session error'
    liveActivity.phase = 'error'
    liveActivity.status = 'error'
    liveActivity.summary = `Error: ${truncateText(errorMessage, 88)}`
    liveActivity.current_tool_name = null
    liveActivity.last_event_type = 'error'
  } else if (event.event_type === 'session_start') {
    liveActivity.phase = 'waiting_for_model'
    liveActivity.status = 'active'
    liveActivity.summary = 'Session started'
    liveActivity.last_event_type = 'session_start'
  }

  return {
    ...session,
    updated_at: event.timestamp,
    status:
      event.event_type === 'complete'
        ? 'completed'
        : event.event_type === 'error'
          ? 'failed'
          : session.status,
    live_activity: liveActivity as SessionListItem['live_activity'],
  }
}

function patchSessionList(
  sessions: SessionListItem[],
  event: SessionEvent,
): SessionListItem[] {
  let changed = false
  const patched = sessions.map((session) => {
    if (session.id !== event.session_id) {
      return session
    }
    changed = true
    return patchSessionWithLiveEvent(session, event)
  })
  return changed ? sortSessionsByUpdatedAt(patched) : sessions
}

export interface PersonaRuntimeState {
  primarySession: SessionListItem | null
  primarySessionDetails: Session | null
  activePersonaSessions: SessionListItem[]
  activeChildSessions: SessionListItem[]
  loading: boolean
  error: string | null
  stoppingSessionId: string | null
  runtimeSyncKey: string
  refresh: () => Promise<void>
  stopSession: (sessionId: string) => Promise<boolean>
  stopCurrentStream: () => Promise<boolean>
  stopActiveWork: () => Promise<{ cancelled: number; attempted: number }>
}

export function usePersonaRuntime(
  preferredSessionId: string | null = null,
): PersonaRuntimeState {
  const [activePersonaSessions, setActivePersonaSessions] = useState<
    SessionListItem[]
  >([])
  const [activeChildSessions, setActiveChildSessions] = useState<
    SessionListItem[]
  >([])
  const [primarySessionDetails, setPrimarySessionDetails] =
    useState<Session | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshTick, setRefreshTick] = useState(0)
  const [stoppingSessionId, setStoppingSessionId] = useState<string | null>(
    null,
  )
  const trackedParentSessionId =
    (
      primarySessionDetails as
        | (Session & Partial<Pick<SessionListItem, 'parent_session_id'>>)
        | null
    )?.parent_session_id ?? preferredSessionId

  const refresh = useCallback(async () => {
    try {
      const data = await fetchSessions({ status: 'active', page_size: 100 })
      const personaSessions = data.sessions
        .filter((session) => session.agent_slug === 'persona')
        .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at))
      const personaIds = new Set(personaSessions.map((session) => session.id))
      if (trackedParentSessionId) {
        personaIds.add(trackedParentSessionId)
      }
      const childSessions = data.sessions
        .filter(
          (session) =>
            session.parent_session_id &&
            personaIds.has(session.parent_session_id) &&
            session.agent_slug !== 'persona',
        )
        .sort((a, b) => +new Date(b.updated_at) - +new Date(a.updated_at))

      setActivePersonaSessions(personaSessions)
      setActiveChildSessions(childSessions)
      setError(null)
    } catch (err) {
      setError(
        err instanceof Error ? err.message : 'Failed to load persona runtime',
      )
    } finally {
      setLoading(false)
    }
  }, [trackedParentSessionId])

  const watchedSessionIds = useMemo(
    () =>
      Array.from(
        new Set([
          ...activePersonaSessions.map((session) => session.id),
          ...activeChildSessions.map((session) => session.id),
          ...(preferredSessionId ? [preferredSessionId] : []),
        ]),
      ),
    [activePersonaSessions, activeChildSessions, preferredSessionId],
  )

  const { status: liveEventsStatus } = useSessionEvents({
    sessionIds: watchedSessionIds,
    autoConnect: true,
    autoReconnect: true,
    onEvent: (event) => {
      let matched = false
      setActivePersonaSessions((current) => {
        const next = patchSessionList(current, event)
        matched = matched || next !== current
        return next
      })
      setActiveChildSessions((current) => {
        const next = patchSessionList(current, event)
        matched = matched || next !== current
        return next
      })
      if (!matched) {
        setRefreshTick((value) => value + 1)
        return
      }
      if (
        event.event_type === 'complete' ||
        event.event_type === 'error' ||
        event.event_type === 'session_start'
      ) {
        window.setTimeout(() => {
          setRefreshTick((value) => value + 1)
        }, 700)
      }
    },
  })

  useEffect(() => {
    refresh()
  }, [refresh, refreshTick])

  useEffect(() => {
    const hasActiveWork =
      activePersonaSessions.length > 0 || activeChildSessions.length > 0
    const interval = window.setInterval(
      () => setRefreshTick((value) => value + 1),
      hasActiveWork ? ACTIVE_POLL_MS : IDLE_POLL_MS,
    )
    return () => window.clearInterval(interval)
  }, [
    activePersonaSessions.length,
    activeChildSessions.length,
    liveEventsStatus,
  ])

  const primarySession = useMemo(() => {
    if (preferredSessionId) {
      const preferredPersonaSession = activePersonaSessions.find(
        (session) => session.id === preferredSessionId,
      )
      if (preferredPersonaSession) {
        return preferredPersonaSession
      }
      const preferredChildSession = activeChildSessions.find(
        (session) => session.id === preferredSessionId,
      )
      if (preferredChildSession) {
        return preferredChildSession
      }
    }
    if (activePersonaSessions.length > 0) {
      return activePersonaSessions[0]
    }
    if (activeChildSessions.length > 0) {
      return activeChildSessions[0]
    }
    return null
  }, [activeChildSessions, activePersonaSessions, preferredSessionId])

  const runtimeSyncKey = useMemo(() => {
    const personaKey = activePersonaSessions
      .map((session) => `${session.id}:${session.updated_at}`)
      .join('|')
    const childKey = activeChildSessions
      .map((session) => `${session.id}:${session.updated_at}`)
      .join('|')
    return `${personaKey}::${childKey}`
  }, [activeChildSessions, activePersonaSessions])

  const preferredRuntimeSession = useMemo(
    () =>
      preferredSessionId
        ? ([...activePersonaSessions, ...activeChildSessions].find(
            (session) => session.id === preferredSessionId,
          ) ?? null)
        : null,
    [activeChildSessions, activePersonaSessions, preferredSessionId],
  )

  const detailSessionId = preferredSessionId ?? primarySession?.id ?? null
  const detailSessionUpdatedAt = preferredSessionId
    ? (preferredRuntimeSession?.updated_at ?? null)
    : (primarySession?.updated_at ?? null)

  useEffect(() => {
    let cancelled = false
    if (!detailSessionId) {
      setPrimarySessionDetails(null)
      return
    }
    fetchSession(detailSessionId)
      .then((session) => {
        if (cancelled) {
          return
        }
        const sessionRecord = session as Session &
          Partial<Pick<SessionListItem, 'parent_session_id'>>
        setPrimarySessionDetails((current) =>
          current?.id === session.id &&
          current.updated_at === session.updated_at
            ? current
            : session,
        )
        if (
          preferredSessionId &&
          session.agent_slug === 'persona' &&
          !sessionRecord.parent_session_id &&
          !isRuntimeActive(session)
        ) {
          setRefreshTick((value) => value + 1)
        }
        if (!isRuntimeActive(session)) {
          return
        }
        const sessionListItem = toSessionListItem(session)
        if (
          sessionListItem.parent_session_id &&
          sessionListItem.agent_slug !== 'persona'
        ) {
          setActiveChildSessions((current) =>
            upsertSessionListItem(current, sessionListItem),
          )
          return
        }
        setActivePersonaSessions((current) =>
          upsertSessionListItem(current, sessionListItem),
        )
      })
      .catch(() => {
        if (!cancelled) {
          setPrimarySessionDetails((current) =>
            current?.id === detailSessionId ? null : current,
          )
        }
      })
    return () => {
      cancelled = true
    }
  }, [detailSessionId, detailSessionUpdatedAt])

  const stopSession = useCallback(async (sessionId: string) => {
    setStoppingSessionId(sessionId)
    try {
      const result = await cancelSessionStream(sessionId)
      setRefreshTick((value) => value + 1)
      return result.cancelled
    } finally {
      setStoppingSessionId(null)
    }
  }, [])

  const stopCurrentStream = useCallback(async () => {
    if (!primarySession) {
      return false
    }
    return stopSession(primarySession.id)
  }, [primarySession, stopSession])

  const stopActiveWork = useCallback(async () => {
    const activeSessions = [
      ...activePersonaSessions,
      ...activeChildSessions,
    ].filter(
      (session) =>
        session.status === 'active' ||
        session.live_activity?.status === 'active' ||
        session.live_activity?.phase === 'running_tool' ||
        session.live_activity?.phase === 'waiting_for_model',
    )
    if (activeSessions.length === 0) {
      return { cancelled: 0, attempted: 0 }
    }

    setStoppingSessionId(activeSessions[0]?.id ?? null)
    try {
      const results = await Promise.all(
        activeSessions.map(async (session) => {
          try {
            const result = await cancelSessionStream(session.id)
            return result.cancelled ? 1 : 0
          } catch {
            return 0
          }
        }),
      )
      setRefreshTick((value) => value + 1)
      return {
        cancelled: results.reduce<number>((sum, value) => sum + value, 0),
        attempted: activeSessions.length,
      }
    } finally {
      setStoppingSessionId(null)
    }
  }, [activeChildSessions, activePersonaSessions])

  return {
    primarySession,
    primarySessionDetails,
    activePersonaSessions,
    activeChildSessions,
    loading,
    error,
    stoppingSessionId,
    runtimeSyncKey,
    refresh,
    stopSession,
    stopCurrentStream,
    stopActiveWork,
  }
}
