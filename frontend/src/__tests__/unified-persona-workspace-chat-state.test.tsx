import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnifiedPersonaWorkspace } from "@/app/persona/components/UnifiedPersonaWorkspace";

const mockUseChatStream = vi.fn();
const mockFetchPersonaStream = vi.fn();

vi.mock("@/lib/api/persona-stream", () => ({
  fetchPersonaStream: (...args: unknown[]) => mockFetchPersonaStream(...args),
}));

vi.mock("@/hooks/use-session-events", () => ({
  useSessionEvents: () => ({
    events: [],
    status: "connected",
    error: null,
    subscriptionId: "sub-1",
    connect: vi.fn(),
    disconnect: vi.fn(),
    updateFilters: vi.fn(),
    clearEvents: vi.fn(),
  }),
}));

vi.mock("@/components/error/toast", () => ({
  useToastActions: () => ({
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}));

vi.mock("@/app/persona/components/TimeRangeDropdown", () => ({
  TimeRangeDropdown: () => <div data-testid="time-range">24h</div>,
}));

vi.mock("@/app/persona/hooks/useNarrationTags", () => ({
  useNarrationTags: () => ({
    narrationCache: {},
    fetchNarrationTags: vi.fn(),
  }),
}));

vi.mock("@agent-hub/chat-ui", () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => <div>{message.content}</div>,
  MessageInput: () => <div data-testid="message-input">composer</div>,
  useChatStream: (...args: unknown[]) => mockUseChatStream(...args),
}));

describe("UnifiedPersonaWorkspace chat state", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: "idle",
      error: null,
      currentSessionId: "chat-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });
    mockFetchPersonaStream.mockResolvedValue({
      entries: [],
      total: 0,
      page: 1,
      page_size: 100,
      matches: [],
      match_count: 0,
      pulse: {
        metrics: [],
        issue_groups: [],
        agent_scorecards: [],
      },
    });
  });

  it("hydrates persisted chat sessions when an active session id is present", async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockUseChatStream).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: "chat-1",
          loadInitialSession: true,
          apiConfig: expect.objectContaining({
            completeEndpoint: "/api/complete",
          }),
        }),
      );
    });
  });

  it("keeps brand new threads in non-hydrating mode", async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId={null}
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockUseChatStream).toHaveBeenCalledWith(
        expect.objectContaining({
          sessionId: undefined,
          loadInitialSession: false,
        }),
      );
    });
  });

  it("shows chat errors without pretending the persona is still responding", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: "error",
      error: "Request failed",
      currentSessionId: "chat-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    expect(screen.queryByText(/is responding$/)).not.toBeInTheDocument();
    expect(screen.getByText("Request failed")).toBeInTheDocument();
  });

  it("clears the in-memory session immediately when starting a new thread", async () => {
    const resetSession = vi.fn();
    const onNewSession = vi.fn();
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: "idle",
      error: null,
      currentSessionId: "chat-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession,
    });

    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey=""
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={onNewSession}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /New thread/i }));

    expect(resetSession).toHaveBeenCalledTimes(1);
    expect(onNewSession).toHaveBeenCalledTimes(1);
  });

  it("keeps a brand new live thread visible before runtime polling catches up", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "check summitflow lane state",
          timestamp: new Date("2026-04-15T14:10:00Z"),
        },
        {
          id: "assistant-1",
          role: "assistant",
          content: "",
          timestamp: new Date("2026-04-15T14:10:01Z"),
          toolExecutions: [],
        },
      ],
      status: "streaming",
      error: null,
      currentSessionId: "chat-live-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-1",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId={null}
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-1"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Draft primary thread")).toBeInTheDocument();
    });

    expect(screen.queryByText("Fresh thread")).not.toBeInTheDocument();
    expect(screen.getAllByText("Avery is responding").length).toBeGreaterThan(0);
    expect(screen.getByText("Project · agent-hub")).toBeInTheDocument();
  });

  it("prefers persisted completed session truth over a stale draft shell", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [
        {
          id: "user-1",
          role: "user",
          content: "review operator surface",
          timestamp: new Date("2026-04-15T14:10:00Z"),
        },
        {
          id: "assistant-1",
          role: "assistant",
          content: "Tool run complete. Highest-signal issue: stale session state.",
          timestamp: new Date("2026-04-15T14:10:04Z"),
          toolExecutions: [],
        },
      ],
      status: "idle",
      error: null,
      currentSessionId: "chat-done-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: {
            id: "chat-done-1",
            project_id: "agent-hub",
            provider: "openai",
            model: "gpt-5.4",
            status: "completed",
            agent_slug: "persona",
            session_type: "chat",
            created_at: "2026-04-15T14:10:00Z",
            updated_at: "2026-04-15T14:10:04Z",
            live_activity: {
              phase: "completed",
              status: "completed",
              summary: "Tool run complete. Highest-signal issue: stale session state.",
              health: "ok",
              stalled: false,
              outstanding_tool_calls: 0,
              tool_calls_count: 3,
              files_touched: [],
            },
            context_usage: {
              used_tokens: 2200,
              limit_tokens: 8000,
              percent_used: 28,
              remaining_tokens: 5800,
              warning: null,
            },
            total_input_tokens: 1200,
            total_output_tokens: 350,
            messages: [],
          },
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-done-1",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId="chat-done-1"
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-done-1"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Tool run complete. Highest-signal issue: stale session state.").length).toBeGreaterThan(0);
    });

    expect(screen.queryByText("Waiting for model response")).not.toBeInTheDocument();
    expect(screen.getAllByText("Status · completed").length).toBeGreaterThan(0);
  });

  it("prefers live draft truth when a follow-up is streaming on a completed session", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [
        {
          id: "user-2",
          role: "user",
          content: "continue from claimed lane",
          timestamp: new Date("2026-04-16T01:23:34Z"),
        },
        {
          id: "assistant-2",
          role: "assistant",
          content: "",
          timestamp: new Date("2026-04-16T01:23:35Z"),
          toolExecutions: [{ id: "tool-1", name: "bash", status: "running", input: { command: "pwd" } }],
        },
      ],
      status: "streaming",
      error: null,
      currentSessionId: "chat-done-3",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: {
            id: "chat-done-3",
            project_id: "summitflow",
            provider: "openai",
            model: "gpt-5.4",
            status: "completed",
            agent_slug: "persona",
            session_type: "chat",
            created_at: "2026-04-16T01:06:43Z",
            updated_at: "2026-04-16T01:06:43Z",
            live_activity: {
              phase: "completed",
              status: "completed",
              summary: "Session completed",
              health: "ok",
              stalled: false,
              outstanding_tool_calls: 0,
              tool_calls_count: 9,
              files_touched: [],
            },
            context_usage: {
              used_tokens: 2200,
              limit_tokens: 8000,
              percent_used: 28,
              remaining_tokens: 5800,
              warning: null,
            },
            total_input_tokens: 1200,
            total_output_tokens: 350,
            messages: [],
          },
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-done-3",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId="chat-done-3"
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-done-3"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getAllByText("Running bash").length).toBeGreaterThan(0);
    });

    expect(screen.getAllByText("Status · active").length).toBeGreaterThan(0);
    expect(screen.queryByText("Session completed")).not.toBeInTheDocument();
  });

  it("uses persisted completed session project for follow-up sends", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: "idle",
      error: null,
      currentSessionId: "chat-done-2",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: {
            id: "chat-done-2",
            project_id: "summitflow",
            provider: "openai",
            model: "gpt-5.4",
            status: "completed",
            agent_slug: "persona",
            session_type: "chat",
            created_at: "2026-04-15T14:10:00Z",
            updated_at: "2026-04-15T14:10:04Z",
            live_activity: {
              phase: "completed",
              status: "completed",
              summary: "Completed summitflow thread.",
              health: "ok",
              stalled: false,
              outstanding_tool_calls: 0,
              tool_calls_count: 0,
              files_touched: [],
            },
            context_usage: {
              used_tokens: 2200,
              limit_tokens: 8000,
              percent_used: 28,
              remaining_tokens: 5800,
              warning: null,
            },
            total_input_tokens: 1200,
            total_output_tokens: 350,
            messages: [],
          },
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-done-2",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId="chat-done-2"
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-done-2"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(mockUseChatStream).toHaveBeenCalledWith(
        expect.objectContaining({
          apiConfig: expect.objectContaining({
            projectId: "summitflow",
          }),
        }),
      );
    });
  });

  it("overlays the footer on short viewports so chat space stays alive", async () => {
    const originalHeight = window.innerHeight;
    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: 640,
      writable: true,
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-compact",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId={null}
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-compact"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    window.dispatchEvent(new Event("resize"));

    await waitFor(() => {
      expect(screen.getByTestId("persona-workspace-root")).toHaveAttribute("data-compact-viewport", "true");
    });
    expect(screen.getByTestId("persona-footer-shell").className).toContain("absolute");

    Object.defineProperty(window, "innerHeight", {
      configurable: true,
      value: originalHeight,
      writable: true,
    });
  });

  it("strips observability tags from assistant transcript bubbles", async () => {
    mockUseChatStream.mockReturnValue({
      messages: [
        {
          id: "assistant-clean-1",
          role: "assistant",
          content: "[[P:found]] Clean summary for operator view. Applied: [M:1234abcd] [[S:completed:clean summary]]",
          timestamp: new Date("2026-04-16T02:00:00Z"),
          toolExecutions: [],
        },
      ],
      status: "idle",
      error: null,
      currentSessionId: "chat-clean-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
      resetSession: vi.fn(),
    });

    render(
      <UnifiedPersonaWorkspace
        persona={{
          id: 1,
          name: "Avery",
          personality: null,
          user_profile: null,
          heartbeat_instructions: null,
          user_context: null,
          voice_id: "voice",
          voice_enabled: false,
          heartbeat_interval_minutes: 30,
          execution_state: "active",
          avatar_url: null,
          greeting: null,
          onboarding_complete: true,
          onboarding_phase: "complete",
          onboarding_attempts: 0,
          session_reset_mode: "off",
          session_reset_hour: 9,
          session_reset_idle_minutes: 120,
          limits: null,
          agent_slug: "persona",
          version: 1,
          updated_at: null,
        }}
        personaName="Avery"
        runtime={{
          primarySession: null,
          primarySessionDetails: null,
          activePersonaSessions: [],
          activeChildSessions: [],
          loading: false,
          error: null,
          stoppingSessionId: null,
          runtimeSyncKey: "sync-clean-1",
          refresh: vi.fn().mockResolvedValue(undefined),
          stopSession: vi.fn().mockResolvedValue(true),
          stopCurrentStream: vi.fn().mockResolvedValue(true),
          stopActiveWork: vi.fn().mockResolvedValue({ cancelled: 0, attempted: 0 }),
        }}
        agentSlug="persona"
        activeSessionId={null}
        sidebarRefreshTrigger={0}
        runtimeSyncKey="sync-clean-1"
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("Clean summary for operator view.")).toBeInTheDocument();
    });
    expect(screen.queryByText(/\[\[P:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/\[\[S:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Applied:/)).not.toBeInTheDocument();
  });
});
