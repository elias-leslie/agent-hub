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

  it("preloads the externally selected session before sending without an override", async () => {
    mockLoadSession.mockImplementation(async (requestedSessionId: string) => {
      if (requestedSessionId === "sess-root") {
        return {
          messages: [{ id: "root-msg", role: "user", content: "root context", timestamp: new Date("2026-04-16T00:00:00Z") }],
          projectId: "agent-hub",
        };
      }
      if (requestedSessionId === "sess-child") {
        return {
          messages: [{ id: "child-msg", role: "user", content: "child context", timestamp: new Date("2026-04-16T00:01:00Z") }],
          projectId: "summitflow",
        };
      }
      throw new Error(`Unexpected session ${requestedSessionId}`);
    });

    const { result, rerender } = renderHook(
      ({ currentSessionId }: { currentSessionId: string }) =>
        useChatStream({
          agentSlug: "persona",
          sessionId: currentSessionId,
          loadInitialSession: true,
          toolsEnabled: true,
          apiConfig: {
            projectId: "agent-hub",
            completeEndpoint: "/api/complete",
            sessionsEndpoint: "/api/sessions",
            preferencesEndpoint: "/api/preferences",
          },
        }),
      { initialProps: { currentSessionId: "sess-root" } },
    );

    await waitFor(() => {
      expect(mockLoadSession).toHaveBeenCalledWith("sess-root", expect.any(Function), "/api/sessions");
      expect(result.current.currentSessionId).toBe("sess-root");
      expect(result.current.status).toBe("idle");
    });

    rerender({ currentSessionId: "sess-child" });

    await act(async () => {
      await result.current.sendMessage("Continue the summitflow lane.");
    });

    expect(mockSendMessageImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [expect.objectContaining({ content: "child context" })],
        sessionId: "sess-child",
        projectId: "summitflow",
      }),
    );
  });

  it("retries the selected session load after a session-override preload failure", async () => {
    let rejectChildLoad: ((reason?: unknown) => void) | null = null;
    let childLoadAttempts = 0;
    mockLoadSession.mockImplementation((requestedSessionId: string) => {
      if (requestedSessionId === "sess-root") {
        return Promise.resolve({
          messages: [{ id: "root-msg", role: "user", content: "root context", timestamp: new Date("2026-04-16T00:00:00Z") }],
          projectId: "agent-hub",
        });
      }
      childLoadAttempts += 1;
      if (childLoadAttempts === 1) {
        return new Promise((_, reject) => {
          rejectChildLoad = reject;
        });
      }
      return Promise.reject(new Error("load failed for sess-child"));
    });

    const { result, rerender } = renderHook(
      ({ currentSessionId }: { currentSessionId: string }) =>
        useChatStream({
          agentSlug: "persona",
          sessionId: currentSessionId,
          loadInitialSession: true,
          toolsEnabled: true,
          apiConfig: {
            projectId: "agent-hub",
            completeEndpoint: "/api/complete",
            sessionsEndpoint: "/api/sessions",
            preferencesEndpoint: "/api/preferences",
          },
        }),
      { initialProps: { currentSessionId: "sess-root" } },
    );

    await waitFor(() => {
      expect(result.current.currentSessionId).toBe("sess-root");
      expect(result.current.status).toBe("idle");
    });

    let pendingSend: Promise<void> | undefined;
    await act(async () => {
      const sendFromCurrentThread = result.current.sendMessage as unknown as (
        content: string,
        targetAgents?: string[],
        sessionIdOverride?: string,
      ) => Promise<void>;
      rerender({ currentSessionId: "sess-child" });
      pendingSend = sendFromCurrentThread("Continue the summitflow lane.", undefined, "sess-child");
    });

    await act(async () => {
      rejectChildLoad?.(new Error("load failed for sess-child"));
      await pendingSend?.catch(() => undefined);
    });

    await waitFor(() => {
      expect(mockLoadSession).toHaveBeenCalledTimes(3);
      expect(result.current.status).toBe("error");
      expect(result.current.error).toContain("load failed for sess-child");
    });
    expect(mockSendMessageImpl).not.toHaveBeenCalled();
  });

  it("preloads the target lane before sending a session override", async () => {
    mockLoadSession.mockImplementation(async (requestedSessionId: string) => {
      if (requestedSessionId === "sess-root") {
        return {
          messages: [{ id: "root-msg", role: "user", content: "root context", timestamp: new Date("2026-04-16T00:00:00Z") }],
          projectId: "agent-hub",
        };
      }
      if (requestedSessionId === "sess-child") {
        return {
          messages: [{ id: "child-msg", role: "user", content: "child context", timestamp: new Date("2026-04-16T00:01:00Z") }],
          projectId: "summitflow",
        };
      }
      throw new Error(`Unexpected session ${requestedSessionId}`);
    });

    const { result, rerender } = renderHook(
      ({ currentSessionId }: { currentSessionId: string }) =>
        useChatStream({
          agentSlug: "persona",
          sessionId: currentSessionId,
          loadInitialSession: true,
          toolsEnabled: true,
          apiConfig: {
            projectId: "agent-hub",
            completeEndpoint: "/api/complete",
            sessionsEndpoint: "/api/sessions",
            preferencesEndpoint: "/api/preferences",
          },
        }),
      { initialProps: { currentSessionId: "sess-root" } },
    );

    await waitFor(() => {
      expect(mockLoadSession).toHaveBeenCalledWith("sess-root", expect.any(Function), "/api/sessions");
      expect(result.current.currentSessionId).toBe("sess-root");
      expect(result.current.status).toBe("idle");
    });

    await act(async () => {
      rerender({ currentSessionId: "sess-child" });
      await result.current.sendMessage("Redirect current work: finish the blocker review.", undefined, "sess-child");
    });

    expect(mockSendMessageImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [expect.objectContaining({ content: "child context" })],
        sessionId: "sess-child",
        projectId: "summitflow",
      }),
    );
  });

  it("preloads a session override even when initial session loading is disabled", async () => {
    mockLoadSession.mockResolvedValue({
      messages: [{ id: "child-msg", role: "user", content: "child context", timestamp: new Date("2026-04-16T00:01:00Z") }],
      projectId: "summitflow",
    });

    const { result } = renderHook(() =>
      useChatStream({
        agentSlug: "persona",
        sessionId: undefined,
        loadInitialSession: false,
        toolsEnabled: true,
        apiConfig: {
          projectId: "agent-hub",
          completeEndpoint: "/api/complete",
          sessionsEndpoint: "/api/sessions",
          preferencesEndpoint: "/api/preferences",
        },
      }),
    );

    await act(async () => {
      await result.current.sendMessage("Redirect current work: finish the blocker review.", undefined, "sess-child");
    });

    expect(mockLoadSession).toHaveBeenCalledWith("sess-child", expect.any(Function), "/api/sessions");
    expect(mockSendMessageImpl).toHaveBeenCalledWith(
      expect.objectContaining({
        messages: [expect.objectContaining({ content: "child context" })],
        sessionId: "sess-child",
        projectId: "summitflow",
      }),
    );
  });
});
