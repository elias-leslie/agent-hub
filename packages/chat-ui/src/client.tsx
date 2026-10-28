"use client";

import { createContext, createElement, useContext, type ReactNode } from "react";
import type { AgentHubClient } from "@agent-hub/sdk";

/**
 * The part of an `@agent-hub/sdk` client the chat uses. A full `createClient()` result fits; so does any object
 * with these methods (Aico's renderer passes one that forwards each call to its main process).
 */
export interface ChatHubClient {
  /** Tells apart the model catalogs of different Agent Hubs in the query cache. Optional. */
  readonly baseUrl?: string;
  readonly turns: Pick<AgentHubClient["turns"], "stream" | "attach" | "cancel">;
  readonly sessions: Pick<AgentHubClient["sessions"], "get" | "fork">;
  readonly models: Pick<AgentHubClient["models"], "list">;
}

const ChatClientContext = createContext<ChatHubClient | null>(null);

/** Gives every chat component below it the client, so they need no `client` prop. */
export function ChatClientProvider({ client, children }: { client: ChatHubClient; children?: ReactNode }) {
  return createElement(ChatClientContext.Provider, { value: client }, children);
}

/** The explicit client, else the one from a {@link ChatClientProvider}, else null. */
export function useChatClient(explicit?: ChatHubClient | null): ChatHubClient | null {
  const fromContext = useContext(ChatClientContext);
  return explicit ?? fromContext;
}

/** Like {@link useChatClient}, but throws when there is none: the chat cannot work without one. */
export function useRequiredChatClient(explicit?: ChatHubClient | null): ChatHubClient {
  const client = useChatClient(explicit);
  if (!client) {
    throw new Error("@agent-hub/chat-ui needs an Agent Hub client: pass `client` or wrap the chat in <ChatClientProvider>.");
  }
  return client;
}
