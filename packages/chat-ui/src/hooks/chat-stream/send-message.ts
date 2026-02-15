/**
 * Message sending logic for chat streaming.
 */

import type { ChatMessage, StreamStatus } from "../../types/chat";
import type { StreamState, CompletionRequest, MessageHistoryEntry } from "./types";
import { formatModelName, generateId } from "./utils";
import { processStream } from "./stream-processor";

interface SendMessageParams {
  content: string;
  targetAgents?: string[];
  agentSlug: string;
  messages: ChatMessage[];
  temperature: number;
  sessionId?: string;
  workingDir?: string;
  toolsEnabled: boolean;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setStatus: React.Dispatch<React.SetStateAction<StreamStatus>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>;
  streamStatesRef: React.MutableRefObject<Map<string, StreamState>>;
  abortControllersRef: React.MutableRefObject<AbortController[]>;
  fetchHeaders: Record<string, string>;
  completeEndpoint: string;
  preferencesEndpoint?: string;
  projectId: string;
  memoryGroupPrefix: string;
}

/**
 * Sends a message and processes streaming responses from agents.
 */
export async function sendMessage(params: SendMessageParams): Promise<void> {
  const {
    content,
    targetAgents,
    agentSlug,
    messages,
    temperature,
    sessionId,
    workingDir,
    toolsEnabled,
    setMessages,
    setStatus,
    setError,
    setCurrentSessionId,
    streamStatesRef,
    abortControllersRef,
    fetchHeaders,
    completeEndpoint,
    preferencesEndpoint,
    projectId,
    memoryGroupPrefix,
  } = params;

  setError(null);
  setStatus("connecting");

  const effectiveAgents = targetAgents && targetAgents.length > 0 ? targetAgents : [agentSlug];

  // Add user message
  const userMessage: ChatMessage = {
    id: generateId(),
    role: "user",
    content,
    timestamp: new Date(),
    targetModel: effectiveAgents[0],
  };
  setMessages((prev) => [...prev, userMessage]);

  // Create placeholder assistant messages
  const responseGroupId = effectiveAgents.length > 1 ? generateId() : undefined;
  const assistantIds: string[] = [];

  for (const targetAgent of effectiveAgents) {
    const assistantId = generateId();
    assistantIds.push(assistantId);
    streamStatesRef.current.set(assistantId, { content: "", thinking: "", tools: [] });

    const assistantMessage: ChatMessage = {
      id: assistantId,
      role: "assistant",
      content: "",
      timestamp: new Date(),
      toolExecutions: toolsEnabled ? [] : undefined,
      responseGroupId,
      agentModel: targetAgent,
    };
    setMessages((prev) => [...prev, assistantMessage]);
  }

  // Build message history
  const messageHistory: MessageHistoryEntry[] = messages.map((m) => {
    if (m.role === "assistant" && m.agentModel) {
      const modelName = formatModelName(m.agentModel);
      return { role: m.role, content: `[${modelName}]: ${m.content}` };
    }
    return { role: m.role, content: m.content };
  });
  messageHistory.push({ role: "user", content });

  // Create abort controllers
  const controllers = effectiveAgents.map(() => new AbortController());
  abortControllersRef.current = controllers;

  try {
    setStatus("streaming");

    // Fetch user's tier preference
    let tierPreference: string | undefined;
    if (preferencesEndpoint) {
      try {
        const prefResponse = await fetch(preferencesEndpoint);
        if (prefResponse.ok) {
          const prefData = await prefResponse.json();
          tierPreference = prefData.model_tier_preference;
        }
      } catch (error) {
        console.warn("Failed to load tier preference, using default:", error);
      }
    }

    await Promise.all(
      effectiveAgents.map((targetAgent, index) => {
        const requestBody: CompletionRequest = {
          agent_slug: targetAgent,
          messages: messageHistory,
          temperature,
          session_id: sessionId,
          working_dir: workingDir,
          tools_enabled: toolsEnabled,
          project_id: projectId,
          stream: true,
          use_memory: true,
          memory_group_id: `${memoryGroupPrefix}${targetAgent}`,
          tier_preference: tierPreference,
        };

        const state = streamStatesRef.current.get(assistantIds[index])!;
        return processStream(
          targetAgent,
          assistantIds[index],
          controllers[index],
          requestBody,
          state,
          setMessages,
          setCurrentSessionId,
          fetchHeaders,
          completeEndpoint,
        );
      }),
    );

    setStatus("idle");
  } catch (err: unknown) {
    if (err instanceof Error && err.name === "AbortError") {
      setStatus("idle");
    } else {
      setError(err instanceof Error ? err.message : "Stream connection error");
      setStatus("error");
    }
  } finally {
    abortControllersRef.current = [];
    streamStatesRef.current.clear();
  }
}
