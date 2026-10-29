/**
 * Message sending logic for chat streaming.
 */

import type { ChatHubClient } from "../../client";
import type { ChatMessage, StreamStatus } from "../../types/chat";
import type { StreamState, CompletionRequest, MessageHistoryEntry } from "./types";
import { formatModelName, generateId } from "./utils";
import { processStream } from "./stream-processor";

interface SendMessageParams {
  client: Pick<ChatHubClient, "turns">;
  content: string;
  targetAgents?: string[];
  agentSlug: string;
  includeRoles?: string[];
  promptMode?: CompletionRequest["prompt_mode"];
  useMemory?: boolean;
  messages: ChatMessage[];
  temperature: number;
  sessionId?: string;
  workingDir?: string;
  toolsEnabled: boolean;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setStatus: React.Dispatch<React.SetStateAction<StreamStatus>>;
  setError: React.Dispatch<React.SetStateAction<string | null>>;
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>;
  setTurnPhase?: (phase: string | null) => void;
  streamStatesRef: React.MutableRefObject<Map<string, StreamState>>;
  abortControllersRef: React.MutableRefObject<AbortController[]>;
  projectId: string;
  memoryGroupPrefix: string;
  externalId?: string;
  parentSessionId?: string;
  sourceMetadata?: CompletionRequest["source_metadata"];
  workContext?: CompletionRequest["work_context"];
  thinkingLevel?: string | null;
  currentBranch?: string | null;
  model?: string | null;
}

/**
 * Sends a message and processes streaming responses from agents.
 *
 * A session runs one turn at a time on the server, so several target agents answer one after the other, in the
 * order given, and every answer after the first continues the session the first one opened.
 */
export async function sendMessage(params: SendMessageParams): Promise<void> {
  const {
    client,
    content,
    targetAgents,
    agentSlug,
    includeRoles,
    promptMode,
    useMemory,
    messages,
    temperature,
    sessionId,
    workingDir,
    toolsEnabled,
    setMessages,
    setStatus,
    setError,
    setCurrentSessionId,
    setTurnPhase,
    streamStatesRef,
    abortControllersRef,
    projectId,
    memoryGroupPrefix,
    externalId,
    parentSessionId,
    sourceMetadata,
    workContext,
    thinkingLevel,
    currentBranch,
    model,
  } = params;

  setError(null);
  setStatus("connecting");

  const effectiveAgents =
    targetAgents && targetAgents.length > 0 ? targetAgents : [agentSlug];

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
  const messageHistory: MessageHistoryEntry[] = messages.filter((m) => m.kind !== "compaction").map((m) => {
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

  // The session the answers belong to: the one given, then the one the first answer opens.
  let activeSessionId = sessionId;
  const trackSession: React.Dispatch<React.SetStateAction<string | null>> = (value) => {
    if (typeof value === "string" && value) {
      activeSessionId = value;
    }
    setCurrentSessionId(value);
  };

  try {
    setStatus("streaming");

    for (const [index, targetAgent] of effectiveAgents.entries()) {
      if (controllers[index].signal.aborted) break;
      const requestBody: CompletionRequest = {
        agent_slug: targetAgent,
        // Empty means the agent's canonical routing.
        model: model || undefined,
        include_roles: includeRoles && includeRoles.length > 0 ? includeRoles : undefined,
        prompt_mode: promptMode || undefined,
        messages: messageHistory,
        temperature,
        session_id: activeSessionId,
        working_dir: workingDir,
        tools_enabled: toolsEnabled,
        // Streaming tool execution keys off execute_tools; Agent Hub owns the
        // generous internal turn fuse.
        execute_tools: toolsEnabled,
        project_id: projectId,
        external_id: externalId,
        parent_session_id: parentSessionId,
        source_metadata: sourceMetadata,
        work_context: workContext,
        thinking_level: thinkingLevel || undefined,
        current_branch: currentBranch || undefined,
        use_memory: useMemory ?? true,
        memory_group_id: `${memoryGroupPrefix}${targetAgent}`,
      };

      const outcome = await processStream(
        client,
        requestBody,
        {
          assistantId: assistantIds[index],
          streamState: streamStatesRef.current.get(assistantIds[index])!,
          setMessages,
          setCurrentSessionId: trackSession,
          setStatus,
          setTurnPhase,
        },
        controllers[index].signal,
      );
      if (outcome === "cancelled") break;
    }

    if (abortControllersRef.current === controllers) setStatus("idle");
  } catch (err: unknown) {
    // A newer sendMessage (user interruption) owns status now; don't clobber it.
    if (abortControllersRef.current !== controllers) return;
    if (err instanceof Error && err.name === "AbortError") {
      // The connection was dropped here (cancel, unmount, new session); the turn may still be running on the server.
      setStatus("idle");
    } else {
      // The turn ended with an error: nothing to resume.
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
