/**
 * SSE stream processing utilities with connect-time retry.
 */

import type { ChatMessage, StreamMessage, StreamStatus } from "../../types/chat";
import type { StreamState, CompletionRequest } from "./types";
import { handleStreamEvent } from "./message-handlers";

/**
 * Backoff policy for connect-time retries: exponential backoff + jitter.
 */
const INITIAL_DELAY_MS = 1000;
const MAX_DELAY_MS = 30000;
const BACKOFF_FACTOR = 2;
const JITTER_FACTOR = 0.2;

function computeBackoffDelay(attempt: number): number {
  const base = Math.min(INITIAL_DELAY_MS * BACKOFF_FACTOR ** Math.max(attempt - 1, 0), MAX_DELAY_MS);
  const jitter = base * JITTER_FACTOR * Math.random();
  return Math.round(base + jitter);
}

/**
 * Raised once the backend has accepted the request. The backend has no resume
 * contract, so re-POSTing would start a second run (duplicate tool execution
 * and persisted turns); these failures surface to the user instead.
 */
export class StreamInterruptedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "StreamInterruptedError";
  }
}

function isRetryableError(err: unknown): boolean {
  if (err instanceof Error && err.name === "AbortError") return false;
  if (err instanceof StreamInterruptedError) return false;
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
    throw new StreamInterruptedError("No response body");
  }

  try {
    await readStream(response.body, assistantId, streamState, setMessages, setCurrentSessionId);
  } catch (err) {
    if (err instanceof Error && err.name === "AbortError") throw err;
    throw new StreamInterruptedError(
      err instanceof Error ? err.message : "Stream connection lost",
    );
  }
}

async function readStream(
  body: ReadableStream<Uint8Array>,
  assistantId: string,
  streamState: StreamState,
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>,
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>,
): Promise<void> {
  const reader = body.getReader();
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

      let data: StreamMessage;
      try {
        data = JSON.parse(dataStr) as StreamMessage;
      } catch (parseError) {
        console.warn("Failed to parse SSE data:", dataStr, parseError);
        continue;
      }
      if (data.seq != null && data.seq <= streamState.lastSeq) continue;
      if (data.seq != null) streamState.lastSeq = data.seq;
      // Backend "error" events throw here and must reach the caller.
      handleStreamEvent(
        data,
        assistantId,
        streamState,
        setMessages,
        setCurrentSessionId,
      );
    }
  }

  // Process any remaining buffered content after stream ends
  if (buffer.trim() && buffer.startsWith("data: ")) {
    const dataStr = buffer.slice(6);
    if (dataStr !== "[DONE]") {
      let data: StreamMessage | null = null;
      try {
        data = JSON.parse(dataStr) as StreamMessage;
      } catch {
        // Incomplete final event — nothing to do
      }
      if (data && (data.seq == null || data.seq > streamState.lastSeq)) {
        if (data.seq != null) streamState.lastSeq = data.seq;
        handleStreamEvent(data, assistantId, streamState, setMessages, setCurrentSessionId);
      }
    }
  }
}

/**
 * Wraps processStream with retries for failures before the backend accepts
 * the request (network errors, 5xx, 429), with exponential backoff capped at
 * 30 seconds. User aborts, 4xx errors, and anything after the stream starts
 * (StreamInterruptedError) are NOT retried, because a retry would re-run the
 * whole completion.
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
  let attempt = 0;

  while (!controller.signal.aborted) {
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
      return; // Stream completed successfully — exit
    } catch (err) {
      if (controller.signal.aborted) throw err;
      if (!isRetryableError(err)) throw err;

      attempt += 1;
      const delay = computeBackoffDelay(attempt);
      console.warn(
        `SSE stream error (attempt ${attempt}), retrying in ${delay}ms:`,
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

  throw new DOMException("Aborted", "AbortError");
}
