import { render, screen, waitFor } from "@testing-library/react";
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
});
