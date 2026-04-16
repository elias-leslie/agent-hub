import { describe, expect, it, vi } from "vitest";

import { sendMessage } from "../../../packages/chat-ui/src/hooks/chat-stream/send-message";

const mockProcessStreamWithReconnect = vi.fn();

vi.mock("../../../packages/chat-ui/src/hooks/chat-stream/stream-processor", () => ({
  processStreamWithReconnect: (...args: unknown[]) => mockProcessStreamWithReconnect(...args),
}));

describe("chat stream sendMessage", () => {
  it("requests real tool execution when tools are enabled", async () => {
    mockProcessStreamWithReconnect.mockResolvedValue(undefined);

    await sendMessage({
      content: "Inspect repo and fix the issue.",
      agentSlug: "persona",
      messages: [],
      temperature: 0.2,
      toolsEnabled: true,
      setMessages: vi.fn(),
      setStatus: vi.fn(),
      setError: vi.fn(),
      setCurrentSessionId: vi.fn(),
      streamStatesRef: {
        current: new Map([["assistant-1", { content: "", thinking: "", tools: [], lastSeq: 0 }]]),
      },
      abortControllersRef: { current: [] },
      fetchHeaders: {},
      completeEndpoint: "/api/complete",
      preferencesEndpoint: "/api/preferences",
      projectId: "summitflow",
      memoryGroupPrefix: "agent:",
    });

    expect(mockProcessStreamWithReconnect).toHaveBeenCalledWith(
      "persona",
      expect.any(String),
      expect.any(AbortController),
      expect.objectContaining({
        project_id: "summitflow",
        tools_enabled: true,
        execute_tools: true,
        max_turns: 8,
      }),
      expect.any(Object),
      expect.any(Function),
      expect.any(Function),
      expect.any(Function),
      expect.any(Object),
      "/api/complete",
    );
  });
});
