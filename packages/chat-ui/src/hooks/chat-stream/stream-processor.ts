/**
 * SSE stream processing utilities with automatic reconnection.
 */

import type { ChatMessage, StreamMessage, StreamStatus } from "../../types/chat";
import type { StreamState, CompletionRequest } from "./types";
import { handleStreamEvent } from "./message-handlers";

const MAX_RECONNECT_ATTEMPTS = 3;
const INITIAL_DELAY_MS = 1000;
const MAX_DELAY_MS = 10000;
const BACKOFF_FACTOR = 2;
const JITTER_FACTOR = 0.2;

function computeBackoffDelay(attempt: number): number {
  const base = Math.min(INITIAL_DELAY_MS * BACKOFF_FACTOR ** attempt, MAX_DELAY_MS);
  const jitter = base * JITTER_FACTOR * (Math.random() * 2 - 1);
  return Math.round(base + jitter);
}

function isRetryableError(err: unknown): boolean {
  if (err instanceof Error && err.name === "AbortError") return false;
  if (err instanceof TypeError) return true; // Network error (fetch failed)
  if (err instanceof Error) {
    const match = err.message.match(/^HTTP (\d+)/);
    if (match) {
      const status = parseInt(match[1], 10);
      return status >= 500 || status === 429;
    }
    // Stream read errors are retryable
    return true;
  }
  return false;
}

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
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    // Keep the last element — it may be an incomplete line
    buffer = lines.pop() ?? "";

    for (const line of lines) {
      if (!line.trim() || !line.startsWith("data: ")) continue;

      const dataStr = line.slice(6);
      if (dataStr === "[DONE]") break;

      try {
        const data = JSON.parse(dataStr) as StreamMessage;
        // Dedup on reconnect: skip events already processed
        if (data.seq != null && data.seq <= streamState.lastSeq) continue;
        if (data.seq != null) streamState.lastSeq = data.seq;
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

  // Process any remaining buffered content after stream ends
  if (buffer.trim() && buffer.startsWith("data: ")) {
    const dataStr = buffer.slice(6);
    if (dataStr !== "[DONE]") {
      try {
        const data = JSON.parse(dataStr) as StreamMessage;
        if (data.seq == null || data.seq > streamState.lastSeq) {
          if (data.seq != null) streamState.lastSeq = data.seq;
          handleStreamEvent(data, assistantId, streamState, setMessages, setCurrentSessionId);
        }
      } catch {
        // Incomplete final event — nothing to do
      }
    }
  }
}

/**
 * Wraps processStream with automatic reconnection on transient failures.
 * User-initiated aborts and 4xx errors are NOT retried.
 */
export async function processStreamWithReconnect(
  targetAgent: string,
  assistantId: string,
  controller: AbortController,
  requestBody: CompletionRequest,
  streamState: StreamState,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
  setStatus: React.Dispatch<React.SetStateAction<StreamStatus>>,
  fetchHeaders: Record<string, string>,
  completeEndpoint: string,
): Promise<void> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RECONNECT_ATTEMPTS; attempt++) {
    try {
      await processStream(
        targetAgent,
        assistantId,
        controller,
        requestBody,
        streamState,
        setMessages,
        setCurrentSessionId,
        fetchHeaders,
        completeEndpoint,
      );
      return; // Success — exit
    } catch (err) {
      lastError = err;

      if (!isRetryableError(err) || attempt === MAX_RECONNECT_ATTEMPTS) {
        throw err;
      }

      if (controller.signal.aborted) throw err;

      const delay = computeBackoffDelay(attempt);
      console.warn(
        `SSE stream failed (attempt ${attempt + 1}/${MAX_RECONNECT_ATTEMPTS + 1}), ` +
        `retrying in ${delay}ms:`,
        err instanceof Error ? err.message : err,
      );
      setStatus("reconnecting");

      await new Promise<void>((resolve, reject) => {
        const timer = setTimeout(resolve, delay);
        controller.signal.addEventListener("abort", () => {
          clearTimeout(timer);
          reject(new DOMException("Aborted", "AbortError"));
        }, { once: true });
      });
    }
  }

  throw lastError;
}
