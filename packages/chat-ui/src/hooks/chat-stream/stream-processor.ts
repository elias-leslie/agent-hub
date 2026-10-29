/**
 * Runs a turn's events into chat state. Every network call goes through the Agent Hub client: it dedupes events by
 * `seq`, retries the connect step, and reconnects to the running turn when the connection drops. This file only turns
 * its events into messages and status.
 */

import type { IdleEvent, TurnEvent, TurnRequest } from "@agent-hub/sdk";
import type { ChatHubClient } from "../../client";
import type { ChatMessage, StreamMessage, StreamStatus } from "../../types/chat";
import type { CompletionRequest, StreamState } from "./types";
import { handleStreamEvent } from "./message-handlers";
import { phaseForEvent } from "./turn-phase";

/** Retries of the connect step (network, 5xx, 429) before a turn is accepted; the request is never re-sent after. */
export const CONNECT_RETRY = { attempts: 8, initialDelayMs: 1000, maxDelayMs: 30000, jitter: 0.2 } as const;

export interface TurnSink {
  assistantId: string;
  streamState: StreamState;
  setMessages: React.Dispatch<React.SetStateAction<ChatMessage[]>>;
  setCurrentSessionId: React.Dispatch<React.SetStateAction<string | null>>;
  setStatus: React.Dispatch<React.SetStateAction<StreamStatus>>;
  /** Called with the turn's phase after each event that changes it, and with null when the turn ends. */
  setTurnPhase?: (phase: string | null) => void;
}

export type TurnOutcome = "finished" | "cancelled" | "idle";

/** What the client's `onRetry` / `onReattach` callbacks need to do to the UI. */
export function reconnectCallbacks(sink: Pick<TurnSink, "setStatus">, flag: { reconnecting: boolean }) {
  const mark = () => {
    flag.reconnecting = true;
    sink.setStatus("reconnecting");
  };
  return { onRetry: mark, onReattach: mark };
}

/**
 * Applies events until the turn ends. Returns `"finished"` after a terminal event (`"cancelled"` when it was a
 * cancel) and `"idle"` when an attach found no turn running. Backend `error` events and a stream the client could not recover reject.
 */
export async function consumeTurn(
  events: AsyncIterable<TurnEvent | IdleEvent>,
  sink: TurnSink,
  flag: { reconnecting: boolean } = { reconnecting: false },
): Promise<TurnOutcome> {
  let cancelled = false;
  try {
    for await (const event of events) {
      if (event.type === "idle") return "idle";
      if (flag.reconnecting) {
        flag.reconnecting = false;
        sink.setStatus("streaming");
      }
      const phase = phaseForEvent(event as { type: string; tool_name?: string });
      if (phase !== undefined) sink.setTurnPhase?.(phase);
      if (typeof event.seq === "number") sink.streamState.lastSeq = event.seq;
      // Backend "error" events throw here and must reach the caller.
      handleStreamEvent(event as unknown as StreamMessage, sink.assistantId, sink.streamState, sink.setMessages, sink.setCurrentSessionId);
      if (event.type === "cancel_acknowledged") {
        // Stop means stop: whatever a stream still carries after the acknowledgement is not shown.
        cancelled = true;
        break;
      }
    }
    return cancelled ? "cancelled" : "finished";
  } finally {
    sink.setTurnPhase?.(null);
  }
}

/** Starts a turn and follows it to its end. */
export async function processStream(
  client: Pick<ChatHubClient, "turns">,
  request: CompletionRequest,
  sink: TurnSink,
  signal: AbortSignal,
): Promise<TurnOutcome> {
  const flag = { reconnecting: false };
  const events = client.turns.stream(request as unknown as TurnRequest, {
    signal,
    connectRetry: CONNECT_RETRY,
    ...reconnectCallbacks(sink, flag),
  });
  return consumeTurn(events, sink, flag);
}

/** Joins a session's running turn, replaying it from the start, and follows it to its end. */
export async function attachToTurn(
  client: Pick<ChatHubClient, "turns">,
  sessionId: string,
  sink: TurnSink,
  signal: AbortSignal,
): Promise<TurnOutcome> {
  const flag = { reconnecting: false };
  const events = client.turns.attach(sessionId, {
    signal,
    afterSeq: 0,
    connectRetry: CONNECT_RETRY,
    ...reconnectCallbacks(sink, flag),
  });
  return consumeTurn(events, sink, flag);
}
