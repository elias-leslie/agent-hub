'use client'

import {
  type ChatMessage,
  ChatPanel as ChatPanelBase,
  type ChatStreamApiConfig,
} from '@agent-hub/chat-ui'
import {
  type ComponentProps,
  type ComponentType,
  useEffect,
  useMemo,
  useState,
} from 'react'
import {
  fetchApi,
  getApiBaseUrl,
  getCompleteApiUrl,
  getWsUrl,
  INTERNAL_HEADERS,
} from '@/lib/api-config'
import type { Agent, AgentPreview } from '@/types/agent'
import { DebugPanel, type DebugTrace } from './debug-panel/debug-panel'

const VALID_THINKING_LEVELS = new Set([
  'minimal',
  'low',
  'medium',
  'high',
  'ultrathink',
])

interface WorkChatSourceMetadata {
  transport?: string
  surface?: string
  chat_id?: string
  message_id?: string
  pane_id?: string
  source_client?: string
}

interface WorkChatContext {
  mode?: string
  project_id?: string
  project_name?: string
  task_id?: string
  task_title?: string
  task_summary?: string
  feedback_id?: string
  design_id?: string
  artifact_summary?: string
  surface?: string
  pane_id?: string
}

type ExtendedChatStreamApiConfig = ChatStreamApiConfig & {
  parentSessionId?: string
  sourceMetadata?: WorkChatSourceMetadata
  workContext?: WorkChatContext
}

type ExtendedChatPanelBaseProps = ComponentProps<typeof ChatPanelBase> & {
  autoSendPrompt?: string | null
  autoSendKey?: string | number | null
}

const ExtendedChatPanelBase =
  ChatPanelBase as ComponentType<ExtendedChatPanelBaseProps>

export function normalizeThinkingLevel(
  value: string | null | undefined,
): string | null {
  if (!value) return null
  return VALID_THINKING_LEVELS.has(value) ? value : null
}

interface ChatPanelProps {
  agent?: Agent
  agentSlug?: string
  sessionId?: string
  workingDir?: string
  toolsEnabled?: boolean
  onSessionCreated?: (sessionId: string) => void
  onClear?: () => void
  initialPrompt?: string
  autoSendPrompt?: string | null
  autoSendKey?: string | number | null
  projectId?: string
  externalId?: string
  parentSessionId?: string
  sourceMetadata?: WorkChatSourceMetadata
  workContext?: WorkChatContext
  thinkingLevel?: string | null
  currentBranch?: string | null
}

export function ChatPanel({
  agent,
  agentSlug,
  sessionId,
  workingDir,
  toolsEnabled,
  onSessionCreated,
  onClear,
  initialPrompt,
  autoSendPrompt,
  autoSendKey,
  projectId = 'agent-hub',
  externalId,
  parentSessionId,
  sourceMetadata,
  workContext,
  thinkingLevel,
  currentBranch,
}: ChatPanelProps) {
  const [agentPreview, setAgentPreview] = useState<AgentPreview | undefined>(
    undefined,
  )
  const [messages, setMessages] = useState<ChatMessage[]>([])

  useEffect(() => {
    if (agent) {
      fetchApi(`${getApiBaseUrl()}/api/agents/${agent.slug}/preview`)
        .then((res) => (res.ok ? res.json() : null))
        .then((data) => setAgentPreview(data))
        .catch((err) => console.error('Failed to fetch agent preview:', err))
    }
  }, [agent])

  const debugTrace: DebugTrace | null = useMemo(() => {
    const lastAssistantMessage = [...messages]
      .reverse()
      .find((m) => m.role === 'assistant')
    if (!lastAssistantMessage) return null
    if (!lastAssistantMessage.inputTokens && !lastAssistantMessage.outputTokens)
      return null

    return {
      model_used:
        lastAssistantMessage.agentModel || agent?.primary_model_id || 'unknown',
      input_tokens: lastAssistantMessage.inputTokens || 0,
      output_tokens: lastAssistantMessage.outputTokens || 0,
      latency_ms: lastAssistantMessage.latency || 0,
      mandates_injected: agentPreview?.mandate_count || 0,
      mandate_uuids: agentPreview?.mandate_uuids || [],
      combined_prompt_length: agentPreview?.combined_prompt.length || 0,
    }
  }, [messages, agent, agentPreview])

  const voiceWsUrl = useMemo(
    () =>
      getWsUrl(
        '/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe',
      ),
    [],
  )
  const ttsBaseUrl = useMemo(
    () => getApiBaseUrl() || window.location.origin,
    [],
  )

  const apiConfig: ExtendedChatStreamApiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: getCompleteApiUrl(),
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: '/api/preferences',
      fetchFn: fetchApi,
      projectId,
      memoryGroupPrefix: 'agent:',
      externalId,
      parentSessionId,
      sourceMetadata,
      workContext,
      thinkingLevel: normalizeThinkingLevel(thinkingLevel),
      currentBranch,
    }),
    [
      projectId,
      externalId,
      parentSessionId,
      sourceMetadata,
      workContext,
      thinkingLevel,
      currentBranch,
    ],
  )

  return (
    <ExtendedChatPanelBase
      agentSlug={agent?.slug || agentSlug}
      sessionId={sessionId}
      workingDir={workingDir}
      toolsEnabled={toolsEnabled}
      onSessionCreated={onSessionCreated}
      onClear={onClear}
      initialPrompt={initialPrompt}
      autoSendPrompt={autoSendPrompt}
      autoSendKey={autoSendKey}
      apiConfig={apiConfig}
      fetchFn={fetchApi}
      voiceWsUrl={voiceWsUrl}
      ttsBaseUrl={ttsBaseUrl}
      renderDebugPanel={
        agent
          ? ({ messages: msgs }) => (
              <DebugPanel
                agent={agent}
                preview={agentPreview}
                debugTrace={debugTrace}
                messages={msgs}
              />
            )
          : undefined
      }
      onMessagesChange={setMessages}
    />
  )
}
