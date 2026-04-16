import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { usePersonaRuntime } from "@/app/persona/hooks/usePersonaRuntime";

const mockFetchSessions = vi.fn();
const mockFetchSession = vi.fn();
const mockCancelSessionStream = vi.fn();

vi.mock("@/hooks/use-session-events", () => ({
  useSessionEvents: () => ({
    status: "connected",
  }),
}));

vi.mock("@/lib/api/sessions", () => ({
  fetchSessions: (...args: unknown[]) => mockFetchSessions(...args),
  fetchSession: (...args: unknown[]) => mockFetchSession(...args),
  cancelSessionStream: (...args: unknown[]) => mockCancelSessionStream(...args),
}));

describe("usePersonaRuntime", () => {
  let intervalCallbacks: Array<() => void> = [];

  beforeEach(() => {
    vi.clearAllMocks();
    intervalCallbacks = [];
    vi.spyOn(globalThis, "setInterval").mockImplementation((handler: TimerHandler) => {
      intervalCallbacks.push(handler as () => void);
      return 1 as unknown as ReturnType<typeof setInterval>;
    });
    vi.spyOn(globalThis, "clearInterval").mockImplementation(() => {});
    mockCancelSessionStream.mockResolvedValue({ cancelled: true, session_id: "sess-1" });
    mockFetchSessions.mockResolvedValue({
      sessions: [],
      total: 0,
      page: 1,
      page_size: 100,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("keeps polling active work even when live events stay connected", async () => {
    mockFetchSessions.mockResolvedValue({
      sessions: [
        {
          id: "sess-active",
          project_id: "agent-hub",
          provider: "openai",
          model: "gpt-5.4",
          status: "active",
          agent_slug: "persona",
          session_type: "chat",
          parent_session_id: null,
          external_id: null,
          current_branch: null,
          live_activity: {
            phase: "waiting_for_model",
            status: "active",
            summary: "Waiting for model response",
            health: "ok",
            stalled: false,
            outstanding_tool_calls: 0,
            tool_calls_count: 1,
            files_touched: [],
          },
          message_count: 1,
          total_input_tokens: 100,
          total_output_tokens: 50,
          created_at: "2026-04-15T14:00:00Z",
          updated_at: "2026-04-15T14:00:05Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    });
    mockFetchSession.mockResolvedValue({
      id: "sess-active",
      project_id: "agent-hub",
      provider: "openai",
      model: "gpt-5.4",
      status: "active",
      agent_slug: "persona",
      session_type: "chat",
      created_at: "2026-04-15T14:00:00Z",
      updated_at: "2026-04-15T14:00:05Z",
      live_activity: {
        phase: "waiting_for_model",
        status: "active",
        summary: "Waiting for model response",
        health: "ok",
        stalled: false,
        outstanding_tool_calls: 0,
        tool_calls_count: 1,
        files_touched: [],
      },
      messages: [],
    });

    renderHook(() => usePersonaRuntime());

    await waitFor(() => {
      expect(mockFetchSessions).toHaveBeenCalledTimes(1);
    });

    await act(async () => {
      intervalCallbacks[0]?.();
    });

    await waitFor(() => {
      expect(mockFetchSessions).toHaveBeenCalledTimes(2);
    });
  });

  it("keeps preferred completed session details after active lists empty out", async () => {
    mockFetchSession.mockResolvedValue({
      id: "sess-done",
      project_id: "agent-hub",
      provider: "openai",
      model: "gpt-5.4",
      status: "completed",
      agent_slug: "persona",
      session_type: "chat",
      created_at: "2026-04-15T14:00:00Z",
      updated_at: "2026-04-15T14:00:09Z",
      live_activity: {
        phase: "completed",
        status: "completed",
        summary: "Done",
        health: "ok",
        stalled: false,
        outstanding_tool_calls: 0,
        tool_calls_count: 2,
        files_touched: [],
      },
      messages: [],
    });

    const { result } = renderHook(() => usePersonaRuntime("sess-done"));

    await waitFor(() => {
      expect(mockFetchSession).toHaveBeenCalledWith("sess-done");
    });
    await act(async () => {
      await Promise.resolve();
    });

    expect(result.current.primarySession).toBeNull();
    expect(result.current.primarySessionDetails?.status).toBe("completed");
    expect(result.current.primarySessionDetails?.id).toBe("sess-done");
    expect(result.current.primarySessionDetails?.live_activity?.summary).toBe("Done");
  });

  it("keeps active child sessions visible under a selected completed root thread", async () => {
    mockFetchSessions.mockResolvedValue({
      sessions: [
        {
          id: "child-1",
          project_id: "agent-hub",
          provider: "codex",
          model: "codex/gpt-5.4",
          status: "active",
          agent_slug: "planner",
          session_type: "completion",
          parent_session_id: "sess-done",
          external_id: null,
          current_branch: null,
          live_activity: {
            phase: "waiting_for_model",
            status: "active",
            summary: "Planning operator workflow",
            health: "ok",
            stalled: false,
            outstanding_tool_calls: 0,
            tool_calls_count: 1,
            files_touched: [],
          },
          message_count: 1,
          total_input_tokens: 100,
          total_output_tokens: 50,
          created_at: "2026-04-15T14:00:00Z",
          updated_at: "2026-04-15T14:00:05Z",
        },
      ],
      total: 1,
      page: 1,
      page_size: 100,
    });
    mockFetchSession.mockResolvedValue({
      id: "sess-done",
      project_id: "agent-hub",
      provider: "codex",
      model: "codex/gpt-5.4",
      status: "completed",
      agent_slug: "persona",
      session_type: "chat",
      created_at: "2026-04-15T13:55:00Z",
      updated_at: "2026-04-15T13:59:59Z",
      live_activity: {
        phase: "completed",
        status: "completed",
        summary: "Root done",
        health: "ok",
        stalled: false,
        outstanding_tool_calls: 0,
        tool_calls_count: 1,
        files_touched: [],
      },
      messages: [],
    });

    const { result } = renderHook(() => usePersonaRuntime("sess-done"));
    await act(async () => {
      await result.current.refresh();
    });

    expect(result.current.activeChildSessions[0]?.id).toBe("child-1");
    expect(result.current.activeChildSessions[0]?.parent_session_id).toBe("sess-done");
  });
});
