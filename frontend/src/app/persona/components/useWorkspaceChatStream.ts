"use client";

import { useMemo } from "react";
import { useChatStream } from "@agent-hub/chat-ui";
import { INTERNAL_HEADERS, fetchApi, getApiBaseUrl, getCompleteApiUrl } from "@/lib/api-config";
import { PROJECT_ID } from "./workspace-types";

export interface WorkspaceChatStreamOptions {
  agentSlug: string;
  personaDisplayName: string;
  activeSessionId: string | null;
}

export function useWorkspaceChatStream({
  agentSlug,
  personaDisplayName,
  activeSessionId,
}: WorkspaceChatStreamOptions) {
  const apiConfig = useMemo(
    () => ({
      fetchHeaders: INTERNAL_HEADERS,
      completeEndpoint: getCompleteApiUrl(),
      sessionsEndpoint: `${getApiBaseUrl()}/api/sessions`,
      preferencesEndpoint: "/api/preferences",
      fetchFn: fetchApi,
      projectId: PROJECT_ID,
      memoryGroupPrefix: "agent:",
    }),
    [],
  );

  const { messages, status, error: chatError, currentSessionId, sendMessage, cancelStream } = useChatStream({
    agentSlug,
    sessionId: activeSessionId || undefined,
    toolsEnabled: true,
    apiConfig,
    loadInitialSession: Boolean(activeSessionId),
  });

  const responseStatusLabel =
    status === "streaming"
      ? `${personaDisplayName} is responding`
      : status === "reconnecting"
        ? `Reconnecting to ${personaDisplayName}`
        : status === "cancelling"
          ? `Stopping ${personaDisplayName}'s response`
          : null;

  return {
    apiConfig,
    messages,
    status,
    chatError,
    currentSessionId,
    sendMessage,
    cancelStream,
    responseStatusLabel,
  };
}
