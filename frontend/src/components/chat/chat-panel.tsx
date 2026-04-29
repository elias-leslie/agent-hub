"use client";

import { useMemo, useState, useEffect } from "react";
import {
  ChatPanel as ChatPanelBase,
  type ChatMessage,
  type ChatStreamApiConfig,
} from "@agent-hub/chat-ui";
import { DebugPanel, type DebugTrace } from "./debug-panel/debug-panel";
import type { Agent, AgentPreview } from "@/types/agent";
import { getApiBaseUrl, getCompleteApiUrl, getWsUrl, fetchApi, INTERNAL_HEADERS } from "@/lib/api-config";

const VALID_THINKING_LEVELS = new Set(["minimal", "low", "medium", "high", "ultrathink"]);

export function normalizeThinkingLevel(value: string | null | undefined): string | null {
  if (!value) return null;
  return VALID_THINKING_LEVELS.has(value) ? value : null;
}

interface ChatPanelProps {
  agent?: Agent;
  agentSlug?: string;
  sessionId?: string;
  workingDir?: string;
  toolsEnabled?: boolean;
  onSessionCreated?: (sessionId: string) => void;
  onClear?: () => void;
  initialPrompt?: string;
  projectId?: string;
  externalId?: string;
  thinkingLevel?: string | null;
  currentBranch?: string | null;
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
  projectId = "agent-hub",
  externalId,
  thinkingLevel,
  currentBranch,
}: ChatPanelProps) {
  const [agentPreview, setAgentPreview] = useState<AgentPreview | undefined>(undefined);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [showDebug, setShowDebug] = useState(false);

  useEffect(() => {
    if (agent && showDebug) {
      fetchApi(`${getApiBaseUrl()}/api/agents/${agent.slug}/preview`)
        .then(res => res.ok ? res.json() : null)
        .then(data => setAgentPreview(data))
        .catch(err => console.error("Failed to fetch agent preview:", err));
    }
  }, [agent, showDebug]);

  const debugTrace: DebugTrace | null = useMemo(() => {
    const lastAssistantMessage = [...messages].reverse().find(m => m.role === "assistant");
    if (!lastAssistantMessage) return null;
    if (!lastAssistantMessage.inputTokens && !lastAssistantMessage.outputTokens) return null;

    return {
      model_used: lastAssistantMessage.agentModel || agent?.primary_model_id || "unknown",
      input_tokens: lastAssistantMessage.inputTokens || 0,
      output_tokens: lastAssistantMessage.outputTokens || 0,
      latency_ms: lastAssistantMessage.latency || 0,
      mandates_injected: agentPreview?.mandate_count || 0,
      mandate_uuids: agentPreview?.mandate_uuids || [],
      combined_prompt_length: agentPreview?.combined_prompt.length || 0,
    };
  }, [messages, agent, agentPreview]);

  const voiceWsUrl = useMemo(
    () => getWsUrl('/api/voice/ws?user_id=agent_hub_user&app=agent-hub&mode=transcribe'),
    []
  );
  const ttsBaseUrl = useMemo(() => getApiBaseUrl() || window.location.origin, []);

  const apiConfig: ChatStreamApiConfig = useMemo(() => ({
    fetchHeaders: INTERNAL_HEADERS,
    completeEndpoint: getCompleteApiUrl(),
    sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
    preferencesEndpoint: "/api/preferences",
    fetchFn: fetchApi,
    projectId,
    memoryGroupPrefix: "agent:",
    externalId,
    thinkingLevel: normalizeThinkingLevel(thinkingLevel),
    currentBranch,
  }), [projectId, externalId, thinkingLevel, currentBranch]);

  return (
    <ChatPanelBase
      agentSlug={agent?.slug || agentSlug}
      sessionId={sessionId}
      workingDir={workingDir}
      toolsEnabled={toolsEnabled}
      onSessionCreated={onSessionCreated}
      onClear={onClear}
      initialPrompt={initialPrompt}
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
  );
}
