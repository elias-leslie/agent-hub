'use client'

import { useChatStream } from '@agent-hub/chat-ui'
import { useMemo } from 'react'
import {
  fetchApi,
  getApiBaseUrl,
  getCompleteApiUrl,
  INTERNAL_HEADERS,
} from '@/lib/api-config'

export interface WorkspaceChatStreamOptions {
  agentSlug: string
  personaDisplayName: string
  activeSessionId: string | null
  projectId: string
}

export function useWorkspaceChatStream({
  agentSlug,
  personaDisplayName,
  activeSessionId,
  projectId,
}: WorkspaceChatStreamOptions) {
  const apiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: getCompleteApiUrl(),
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: '/api/preferences',
      fetchFn: fetchApi,
      projectId,
      memoryGroupPrefix: 'agent:',
    }),
    [projectId],
  )

  const {
    messages,
    status,
    error: chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
    resetSession,
  } = useChatStream({
    agentSlug,
    sessionId: activeSessionId || undefined,
    toolsEnabled: true,
    apiConfig,
    loadInitialSession: Boolean(activeSessionId),
  })

  const responseStatusLabel =
    status === 'streaming'
      ? `${personaDisplayName} is responding`
      : status === 'reconnecting'
        ? `Reconnecting to ${personaDisplayName}`
        : status === 'cancelling'
          ? `Stopping ${personaDisplayName}'s response`
          : null

  return {
    apiConfig,
    messages,
    status,
    chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
    resetSession,
    responseStatusLabel,
  }
}
