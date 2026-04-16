import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";

import { useChatStream } from "../../../packages/chat-ui/src/hooks/use-chat-stream";

const mockLoadSession = vi.fn();
const mockSendMessageImpl = vi.fn();

vi.mock("../../../packages/chat-ui/src/hooks/chat-stream/session-loader", () => ({
  loadSession: (...args: unknown[]) => mockLoadSession(...args),
}));

vi.mock("../../../packages/chat-ui/src/hooks/chat-stream/send-message", () => ({
  sendMessage: (...args: unknown[]) => mockSendMessageImpl(...args),
}));

describe("useChatStream project binding", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockSendMessageImpl.mockResolvedValue(undefined);
  });

  it("binds follow-up sends to the loaded session project", async () => {
    mockLoadSession.mockResolvedValue({
      messages: [],
      projectId: "summitflow",
    });

    const { result } = renderHook(() =>
      useChatStream({
        agentSlug: "persona",
        sessionId: "sess-summitflow",
        loadInitialSession: true,
        toolsEnabled: true,
        apiConfig: {
          projectId: "agent-hub",
          completeEndpoint: "/api/complete",
          sessionsEndpoint: "/api/sessions",
          preferencesEndpoint: "/api/preferences",
        },
      }),
    );

    await waitFor(() => {
      expect(mockLoadSession).toHaveBeenCalledWith("sess-summitflow", expect.any(Function), "/api/sessions");
      expect(result.current.currentSessionId).toBe("sess-summitflow");
      expect(result.current.status).toBe("idle");
    });

    await act(async () => {
      await result.current.sendMessage("take the next summitflow task");
    });

    expect(mockSendMessageImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        sessionId: "sess-summitflow",
        projectId: "summitflow",
      }),
    );
  });
});
