/**
 * SSE stream processing utilities.
 */

import type { ChatMessage, StreamMessage } from "../../types/chat";
import type { StreamState, CompletionRequest } from "./types";
import { handleStreamEvent } from "./message-handlers";

/**
 * Processes an SSE stream for a single agent response.
 */
export async function processStream(
  targetAgent: string,
  assistantId: string,
  controller: AbortController,
  requestBody: CompletionRequest,
  streamState: StreamState,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
  fetchHeaders: Record<string, string>,
  completeEndpoint: string,
): Promise<void> {
  const response = await fetch(completeEndpoint, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...fetchHeaders,
    },
    body: JSON.stringify(requestBody),
    signal: controller.signal,
  });

  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }

  if (!response.body) {
    throw new Error("No response body");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    const chunk = decoder.decode(value, { stream: true });
    const lines = chunk.split("\n");

    for (const line of lines) {
      if (!line.trim() || !line.startsWith("data: ")) continue;

      const dataStr = line.slice(6);
      if (dataStr === "[DONE]") break;

      try {
        const data = JSON.parse(dataStr) as StreamMessage;
        handleStreamEvent(
          data,
          assistantId,
          streamState,
          setMessages,
          setCurrentSessionId,
        );
      } catch (parseError) {
        console.warn("Failed to parse SSE data:", dataStr, parseError);
      }
    }
  }
}
