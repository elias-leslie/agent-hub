import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnifiedPersonaWorkspace } from "@/app/persona/components/UnifiedPersonaWorkspace";

const mockFetchPersonaStream = vi.fn();
const mockUseChatStream = vi.fn();
const mockFetchSessionEvents = vi.fn();

function buildPulseFields(overrides?: Partial<{
  issue_markers: Array<{
    event_id: string;
    event_type: string;
    created_at: string;
    tool_name: string | null;
    tags: string[];
    primary_tag: string;
    root_causes: string[];
    primary_root_cause: string | null;
    title: string;
    summary: string;
    fingerprint: string | null;
  }>;
  pulse_tags: string[];
  primary_pulse_tag: string | null;
  root_causes: string[];
  primary_root_cause: string | null;
  pulse_summary: string | null;
}>) {
  return {
    issue_markers: [],
    pulse_tags: [],
    primary_pulse_tag: null,
    root_causes: [],
    primary_root_cause: null,
    pulse_summary: null,
    ...overrides,
  };
}

function buildStreamResponse(options?: {
  heartbeatStatus?: "active" | "completed";
  heartbeatLiveStatus?: string | null;
  includeSecondHeartbeat?: boolean;
}) {
  const heartbeatStatus = options?.heartbeatStatus ?? "completed";
  const heartbeatLiveStatus = options?.heartbeatLiveStatus ?? null;
  const entries = [
      {
        id: "m-1",
        entry_type: "message",
        timestamp: "2026-03-09T10:00:00Z",
        session_id: "chat-1",
        parent_session_id: null,
        project_id: "persona-sandbox",
        agent_slug: "persona",
        session_type: "chat",
        status: "completed",
        role: "user",
        content: "pause that task",
        summary_oneliner: null,
        current_branch: null,
        external_id: null,
        model: "claude-sonnet",
        live_summary: null,
        live_status: null,
        message_count: 2,
        tool_count: 0,
        event_previews: [],
        ...buildPulseFields(),
      },
      {
        id: "h-1",
        entry_type: "heartbeat",
        timestamp: "2026-03-09T10:01:00Z",
        session_id: "hb-1",
        parent_session_id: null,
        project_id: "persona-sandbox",
        agent_slug: "persona",
        session_type: "heartbeat",
        status: heartbeatStatus,
        role: null,
        content: null,
        summary_oneliner: "Checked active work",
        current_branch: null,
        external_id: null,
        model: "claude-sonnet",
        live_summary: heartbeatStatus === "active" ? "Running validation" : null,
        live_status: heartbeatLiveStatus,
        message_count: 0,
        tool_count: 3,
        event_previews: [
          {
            id: "preview-h-1",
            event_type: "tool_use",
            created_at: "2026-03-09T10:01:10Z",
            role: null,
            tool_name: "st ready-all",
            content_preview: null,
            tool_input_preview: '{"project":"agent-hub"}',
            tool_output_preview: null,
            duration_ms: null,
            model_used: "claude-sonnet",
          },
        ],
        ...buildPulseFields({
          issue_markers: [
            {
              event_id: "preview-h-issue",
              event_type: "assistant_message",
              created_at: "2026-03-09T10:01:20Z",
              tool_name: null,
              tags: ["warning"],
              primary_tag: "warning",
              root_causes: ["context"],
              primary_root_cause: "context",
              title: "Completed with warnings",
              summary: "The run finished but still needed follow-up.",
              fingerprint: "warning:context",
            },
          ],
          pulse_tags: ["friction", "warning", "recovered"],
          primary_pulse_tag: "warning",
          root_causes: ["context"],
          primary_root_cause: "context",
          pulse_summary: "completed with warnings; recovered before completion",
        }),
      },
      ...(options?.includeSecondHeartbeat
        ? [
            {
              id: "h-2",
              entry_type: "heartbeat",
              timestamp: "2026-03-09T10:03:00Z",
              session_id: "hb-2",
              parent_session_id: null,
              project_id: "persona-sandbox",
              agent_slug: "persona",
              session_type: "heartbeat",
              status: "completed",
              role: null,
              content: null,
              summary_oneliner: "Checked backlog state",
              current_branch: null,
              external_id: null,
              model: "claude-sonnet",
              live_summary: null,
              live_status: null,
              message_count: 0,
              tool_count: 1,
              event_previews: [
                {
                  id: "preview-h-2",
                  event_type: "tool_result",
                  created_at: "2026-03-09T10:03:10Z",
                  role: null,
                  tool_name: "st ready-all",
                  content_preview: "No additional work",
                  tool_input_preview: null,
                  tool_output_preview: '{"status":"ok"}',
                  duration_ms: 800,
                  model_used: "claude-sonnet",
                },
              ],
              ...buildPulseFields(),
            },
          ]
        : []),
      {
        id: "c-1",
        entry_type: "child_run",
        timestamp: "2026-03-09T10:02:00Z",
        session_id: "child-1",
        parent_session_id: "hb-1",
        project_id: "agent-hub",
        agent_slug: "git-agent",
        session_type: "completion",
        status: "completed",
        role: null,
        content: null,
        summary_oneliner: "Updated files",
        current_branch: "task-branch",
        external_id: "task-123",
        model: "claude-sonnet",
        live_summary: null,
        live_status: null,
        message_count: 1,
        tool_count: 2,
        event_previews: [
          {
            id: "preview-c-1",
            event_type: "tool_result",
            created_at: "2026-03-09T10:02:10Z",
            role: null,
            tool_name: "dt -q -d",
            content_preview: "passed",
            tool_input_preview: null,
            tool_output_preview: '{"status":"ok"}',
            duration_ms: 1200,
            model_used: "claude-sonnet",
          },
        ],
        ...buildPulseFields({
          issue_markers: [
            {
              event_id: "preview-c-issue",
              event_type: "tool_result",
              created_at: "2026-03-09T10:02:10Z",
              tool_name: "dt -q -d",
              tags: ["tool_friction", "retries"],
              primary_tag: "tool_friction",
              root_causes: ["tool"],
              primary_root_cause: "tool",
              title: "dt -q -d hit tool friction",
              summary: "The tool path wasted turns before progress resumed.",
              fingerprint: "tool-friction:dt-q-d",
            },
          ],
          pulse_tags: ["friction", "tool_friction", "retries"],
          primary_pulse_tag: "tool_friction",
          root_causes: ["tool"],
          primary_root_cause: "tool",
          pulse_summary: "dt -q -d hit repeated tool friction; retried repeated steps",
        }),
      },
    ];
  return {
    entries,
    total: entries.length,
    page: 1,
    page_size: 100,
    matches: [
      {
        entry_id: "h-1",
        session_id: "hb-1",
        entry_type: "heartbeat",
        timestamp: "2026-03-09T10:01:00Z",
        snippet: "Checked active work",
      },
    ],
    match_count: 1,
    pulse: {
      metrics: [
        {
          key: "friction",
          label: "Friction",
          count: 2,
          description: "Sessions that showed warnings, failures, stalls, or other operational drag.",
        },
        {
          key: "warning",
          label: "Warnings",
          count: 1,
          description: "Runs that completed but still reported warnings or blockers.",
        },
        {
          key: "tool_friction",
          label: "Tool Friction",
          count: 1,
          description: "Runs where tools failed, were missing, or wasted turns before progress resumed.",
        },
        {
          key: "recovered",
          label: "Recovered",
          count: 1,
          description: "Runs that hit trouble but still recovered before finishing.",
        },
      ],
      issue_groups: [
        {
          fingerprint: "tool-friction:dt-q-d",
          title: "dt -q -d kept failing or wasting turns",
          summary: "dt -q -d hit repeated tool friction",
          count: 1,
          primary_tag: "tool_friction",
          root_cause: "tool",
          agent_slugs: ["git-agent"],
          latest_entry_id: "c-1",
          latest_session_id: "child-1",
          latest_timestamp: "2026-03-09T10:02:00Z",
        },
      ],
      agent_scorecards: [
        {
          agent_slug: "git-agent",
          label: "git agent",
          session_count: 1,
          success_count: 1,
          friction_count: 1,
          error_count: 0,
          recovered_count: 0,
          stalled_count: 0,
          instruction_drift_count: 0,
          tool_friction_count: 1,
          median_runtime_seconds: 90,
          top_issue: "dt -q -d kept failing or wasting turns",
          top_root_cause: "tool",
        },
      ],
    },
  };
}

vi.mock("@/lib/api/persona-stream", () => ({
  fetchPersonaStream: (...args: unknown[]) => mockFetchPersonaStream(...args),
}));

vi.mock("@/lib/api/sessions", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api/sessions")>("@/lib/api/sessions");
  return {
    ...actual,
    fetchSessionEvents: (...args: unknown[]) => mockFetchSessionEvents(...args),
  };
});

vi.mock("@/components/chat/session-dropdown", () => ({
  SessionDropdown: () => <div data-testid="session-dropdown">sessions</div>,
}));

vi.mock("@/app/persona/components/TimeRangeDropdown", () => ({
  TimeRangeDropdown: () => <div data-testid="time-range">24h</div>,
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

vi.mock("@agent-hub/chat-ui", () => ({
  MessageBubble: ({ message }: { message: { content: string } }) => <div>{message.content}</div>,
  MessageInput: () => <div data-testid="message-input">composer</div>,
  useChatStream: (...args: unknown[]) => mockUseChatStream(...args),
}));

describe("UnifiedPersonaWorkspace", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mockUseChatStream.mockReturnValue({
      messages: [],
      status: "idle",
      error: null,
      currentSessionId: "chat-1",
      sendMessage: vi.fn(),
      cancelStream: vi.fn(),
    });
    mockFetchPersonaStream.mockResolvedValue(buildStreamResponse());
    mockFetchSessionEvents.mockImplementation(async (sessionId: string) => {
      if (sessionId === "hb-1") {
        return {
          session_id: "hb-1",
          total: 3,
          max_turn: 1,
          events: [
            {
              id: "evt-h-0",
              turn: 1,
              sequence: 0,
              event_type: "system_message",
              role: "system",
              content: "# PERSONA SAFETY BOUNDARIES\n<heartbeat_instructions>\nKeep every raw heartbeat detail forever.",
              tool_name: null,
              tool_input: null,
              tool_output: null,
              tokens: null,
              duration_ms: null,
              model_used: "claude-sonnet",
              agent_id: null,
              agent_name: null,
              created_at: "2026-03-09T10:01:09Z",
            },
            {
              id: "evt-h-1",
              turn: 1,
              sequence: 1,
              event_type: "tool_use",
              role: null,
              content: null,
              tool_name: "st ready-all",
              tool_input: { project: "agent-hub", command: "st ready-all --compact" },
              tool_output: null,
              tokens: null,
              duration_ms: null,
              model_used: "claude-sonnet",
              agent_id: null,
              agent_name: null,
              created_at: "2026-03-09T10:01:10Z",
            },
            {
              id: "evt-h-2",
              turn: 1,
              sequence: 2,
              event_type: "tool_result",
              role: null,
              content: null,
              tool_name: "st ready-all",
              tool_input: null,
              tool_output: { status: "ok", content: "Ready queue is clear" },
              tokens: null,
              duration_ms: 900,
              model_used: "claude-sonnet",
              agent_id: null,
              agent_name: null,
              created_at: "2026-03-09T10:01:11Z",
            },
          ],
        };
      }
      if (sessionId === "hb-2") {
        return {
          session_id: "hb-2",
          total: 1,
          max_turn: 1,
          events: [
            {
              id: "evt-h-3",
              turn: 1,
              sequence: 1,
              event_type: "tool_result",
              role: null,
              content: null,
              tool_name: "st ready-all",
              tool_input: null,
              tool_output: { status: "ok", content: "No additional work" },
              tokens: null,
              duration_ms: 800,
              model_used: "claude-sonnet",
              agent_id: null,
              agent_name: null,
              created_at: "2026-03-09T10:03:10Z",
            },
          ],
        };
      }
      return {
        session_id: "child-1",
        total: 2,
        max_turn: 1,
        events: [
          {
            id: "evt-c-1",
            turn: 1,
            sequence: 1,
            event_type: "tool_use",
            role: null,
            content: null,
            tool_name: "dt -q -d",
            tool_input: { command: "dt -q -d", project: "agent-hub" },
            tool_output: null,
            tokens: null,
            duration_ms: null,
            model_used: "claude-sonnet",
            agent_id: null,
            agent_name: null,
            created_at: "2026-03-09T10:02:09Z",
          },
          {
            id: "evt-c-2",
            turn: 1,
            sequence: 2,
            event_type: "tool_result",
            role: null,
            content: null,
            tool_name: "dt -q -d",
            tool_input: null,
            tool_output: { status: "ok", content: "Checks passed", files_touched: ["frontend/src/app/persona/page.tsx"] },
            tokens: null,
            duration_ms: 1200,
            model_used: "claude-sonnet",
            agent_id: null,
            agent_name: null,
            created_at: "2026-03-09T10:02:10Z",
          },
        ],
      };
    });
  });

  it("renders a unified stream with messages, heartbeat summaries, child runs, and composer", async () => {
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
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    expect(screen.getAllByTestId("stream-item")[1]).toHaveTextContent("Checked active work");
    expect(screen.getByText("git-agent on agent-hub")).toBeInTheDocument();
    expect(screen.getByTestId("message-input")).toBeInTheDocument();
    expect(screen.getByTestId("session-dropdown")).toBeInTheDocument();
    expect(screen.getByText("Repeated Friction")).toBeInTheDocument();
    expect(screen.getByText("Agent Scorecards")).toBeInTheDocument();
    expect(screen.getByText("dt -q -d kept failing or wasting turns")).toBeInTheDocument();
    const timelineTimes = document.querySelectorAll("time[datetime]");
    expect(timelineTimes).toHaveLength(3);
  });

  it("filters the timeline from the pulse controls", async () => {
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
      expect(screen.getByText("Tool Friction")).toBeInTheDocument();
    });

    fireEvent.click(screen.getAllByText("Tool Friction")[0]);

    await waitFor(() => {
      expect(screen.queryByText("pause that task")).not.toBeInTheDocument();
    });

    expect(screen.getByText("git-agent on agent-hub")).toBeInTheDocument();
    expect(screen.queryByText("Checked active work")).not.toBeInTheDocument();
    expect(screen.getByText("dt -q -d hit tool friction")).toBeInTheDocument();
  });

  it("renders stream items in chronological order with newest at the bottom", async () => {
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
      expect(screen.getAllByTestId("stream-item")).toHaveLength(3);
    });

    const timestamps = screen
      .getAllByTestId("stream-item")
      .map((item) => item.getAttribute("data-timestamp"));

    expect(timestamps).toEqual([
      "2026-03-09T10:00:00.000Z",
      "2026-03-09T10:01:00.000Z",
      "2026-03-09T10:02:00.000Z",
    ]);
  });

  it("lands at the latest entry on initial load instead of jumping to the active chat session", async () => {
    const scrollToSpy = vi.fn();
    const scrollIntoViewSpy = vi.fn();

    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToSpy,
    });
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoViewSpy,
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

    await waitFor(() => {
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    await waitFor(() => {
      expect(scrollToSpy).toHaveBeenCalled();
    });

    expect(scrollIntoViewSpy).not.toHaveBeenCalled();
  });

  it("nests child runs under their parent work block", async () => {
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
      expect(screen.getByText("Spawned Agents")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Spawned Agents")).toHaveLength(1);
    expect(screen.getByText("git-agent on agent-hub")).toBeInTheDocument();
  });

  it("expands heartbeat and child run details inline", async () => {
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
      expect(screen.getByText("Show heartbeat details")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByText("Show heartbeat details"));
    fireEvent.click(screen.getByText("Show run details"));

    await waitFor(() => {
      expect(mockFetchSessionEvents).toHaveBeenCalledWith("hb-1", { page: 1, page_size: 500 });
      expect(mockFetchSessionEvents).toHaveBeenCalledWith("child-1", { page: 1, page_size: 500 });
    });

    expect(screen.getByText("Ready queue is clear")).toBeInTheDocument();
    expect(screen.getAllByText("Checks passed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Overview").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Issues").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("Important events").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByRole("button", { name: /Show full trace/i })).toBeInTheDocument();
    expect(screen.queryByText(/PERSONA SAFETY BOUNDARIES/i)).not.toBeInTheDocument();
    expect(screen.getAllByText("Completed with warnings").length).toBeGreaterThan(0);
    expect(screen.getByText("dt -q -d hit tool friction")).toBeInTheDocument();
    expect(screen.getAllByText("Warning").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Recovered").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Tool Friction").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Retries").length).toBeGreaterThan(0);
    expect(screen.getAllByText("agent-hub").length).toBeGreaterThan(0);
    expect(screen.getAllByText("ok").length).toBeGreaterThan(0);
    expect(screen.queryByText(/\"status\"/)).not.toBeInTheDocument();

  });

  it("expands only the selected heartbeat detail block", async () => {
    mockFetchPersonaStream.mockResolvedValue(buildStreamResponse({ includeSecondHeartbeat: true }));

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
      expect(screen.getAllByText("Show heartbeat details")).toHaveLength(2);
    });

    fireEvent.click(screen.getAllByText("Show heartbeat details")[0]);

    await waitFor(() => {
      expect(mockFetchSessionEvents).toHaveBeenCalledWith("hb-1", { page: 1, page_size: 500 });
    });

    expect(screen.getAllByText("Hide heartbeat details")).toHaveLength(1);
    expect(screen.getAllByText("Show heartbeat details")).toHaveLength(1);
    expect(screen.getAllByText("Overview")).toHaveLength(1);
    expect(screen.getAllByText("Important events")).toHaveLength(1);
  });

  it("shows search match chips and can jump through them", async () => {
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
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    fireEvent.change(screen.getByPlaceholderText("Search Jenny's history, task IDs, files, agents..."), {
      target: { value: "active work" },
    });

    await waitFor(() => {
      expect(screen.getByText(/1 of 1 matches/)).toBeInTheDocument();
    });

    expect(screen.getByRole("button", { name: /heartbeat.*checkedactivework/i })).toBeInTheDocument();
    expect(mockFetchPersonaStream).toHaveBeenLastCalledWith(
      expect.objectContaining({
        search: "active work",
      }),
    );
  });

  it("turns off auto-follow when the user scrolls up to inspect older work", async () => {
    mockFetchPersonaStream.mockResolvedValue(buildStreamResponse({ heartbeatStatus: "active", heartbeatLiveStatus: "active" }));

    const scrollToSpy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToSpy,
    });

    const { rerender } = render(
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
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    const container = screen.getByTestId("stream-scroll-container");
    Object.defineProperty(container, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(container, "clientHeight", { configurable: true, value: 400 });
    Object.defineProperty(container, "scrollTop", { configurable: true, writable: true, value: 600 });

    await waitFor(() => {
      expect(scrollToSpy).toHaveBeenCalled();
    });

    scrollToSpy.mockClear();
    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 450));
      (container as HTMLDivElement).scrollTop = 120;
      fireEvent.scroll(container);
    });

    expect(screen.getByText("Auto-follow off")).toBeInTheDocument();

    await act(async () => {
      rerender(
        <UnifiedPersonaWorkspace
          agentSlug="persona"
          activeSessionId="chat-1"
          sidebarRefreshTrigger={1}
          runtimeSyncKey=""
          onSelectSession={vi.fn()}
          onSessionCreated={vi.fn()}
          onNewSession={vi.fn()}
        />,
      );
    });

    await waitFor(() => {
      expect(mockFetchPersonaStream).toHaveBeenCalledTimes(2);
    });

    expect(scrollToSpy).not.toHaveBeenCalled();
  });

  it("hides jump-to-latest after the user manually scrolls back to the bottom", async () => {
    const scrollToSpy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollTo", {
      configurable: true,
      value: scrollToSpy,
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

    await waitFor(() => {
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    const container = screen.getByTestId("stream-scroll-container");
    Object.defineProperty(container, "scrollHeight", { configurable: true, value: 1000 });
    Object.defineProperty(container, "clientHeight", { configurable: true, value: 400 });
    Object.defineProperty(container, "scrollTop", { configurable: true, writable: true, value: 600 });

    await act(async () => {
      await new Promise((resolve) => window.setTimeout(resolve, 450));
      (container as HTMLDivElement).scrollTop = 120;
      fireEvent.scroll(container);
    });

    expect(screen.getByText(/Jump to latest/)).toBeInTheDocument();
    expect(screen.getByText("Auto-follow off")).toBeInTheDocument();

    await act(async () => {
      (container as HTMLDivElement).scrollTop = 601;
      fireEvent.scroll(container);
    });

    await waitFor(() => {
      expect(screen.queryByText(/Jump to latest/)).not.toBeInTheDocument();
    });
    expect(screen.getByText("Auto-follow on")).toBeInTheDocument();
  });
});
