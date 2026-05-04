/**
 * Message sending logic for chat streaming.
 */

import type { ChatMessage, StreamStatus } from "../../types/chat";
import type { StreamState, CompletionRequest, MessageHistoryEntry } from "./types";
import { formatModelName, generateId } from "./utils";
import { processStreamWithReconnect } from "./stream-processor";

const TOOL_ENABLED_MAX_TURNS = 80;

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
  externalId?: string;
  parentSessionId?: string;
  sourceMetadata?: CompletionRequest["source_metadata"];
  workContext?: CompletionRequest["work_context"];
  thinkingLevel?: string | null;
  currentBranch?: string | null;
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
    externalId,
    parentSessionId,
    sourceMetadata,
    workContext,
    thinkingLevel,
    currentBranch,
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
    streamStatesRef.current.set(assistantId, { content: "", thinking: "", tools: [], lastSeq: 0 });

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

    await Promise.all(
      effectiveAgents.map((targetAgent, index) => {
        const requestBody: CompletionRequest = {
          agent_slug: targetAgent,
          messages: messageHistory,
          temperature,
          session_id: sessionId,
          working_dir: workingDir,
          tools_enabled: toolsEnabled,
          // Streaming tool execution keys off execute_tools/max_turns on the
          // backend. tools_enabled alone is ignored by the request schema.
          execute_tools: toolsEnabled,
          max_turns: toolsEnabled ? TOOL_ENABLED_MAX_TURNS : 1,
          project_id: projectId,
          external_id: externalId,
          parent_session_id: parentSessionId,
          source_metadata: sourceMetadata,
          work_context: workContext,
          thinking_level: thinkingLevel || undefined,
          current_branch: currentBranch || undefined,
          stream: true,
          use_memory: true,
          memory_group_id: `${memoryGroupPrefix}${targetAgent}`,
        };

        const state = streamStatesRef.current.get(assistantIds[index])!;
        return processStreamWithReconnect(
          targetAgent,
          assistantIds[index],
          controllers[index],
          requestBody,
          state,
          setMessages,
          setCurrentSessionId,
          setStatus,
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
    // Only clean up if these are still our controllers (a new sendMessage
    // call may have already replaced them during user interruption).
    if (abortControllersRef.current === controllers) {
      abortControllersRef.current = [];
      streamStatesRef.current.clear();
    }
  }
}
