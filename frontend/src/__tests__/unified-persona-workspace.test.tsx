import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { UnifiedPersonaWorkspace } from "@/app/persona/components/UnifiedPersonaWorkspace";

const mockFetchPersonaStream = vi.fn();
const mockUseChatStream = vi.fn();

vi.mock("@/lib/api/persona-stream", () => ({
  fetchPersonaStream: (...args: unknown[]) => mockFetchPersonaStream(...args),
}));

vi.mock("@/components/chat/session-dropdown", () => ({
  SessionDropdown: () => <div data-testid="session-dropdown">sessions</div>,
}));

vi.mock("@/app/persona/components/TimeRangeDropdown", () => ({
  TimeRangeDropdown: () => <div data-testid="time-range">24h</div>,
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
    mockFetchPersonaStream.mockResolvedValue({
      entries: [
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
          status: "completed",
          role: null,
          content: null,
          summary_oneliner: "Checked active work",
          current_branch: null,
          external_id: null,
          model: "claude-sonnet",
          live_summary: null,
          live_status: null,
          message_count: 0,
          tool_count: 3,
        },
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
        },
      ],
      total: 3,
      page: 1,
      page_size: 100,
    });
  });

  it("renders a unified stream with messages, heartbeat summaries, child runs, and composer", async () => {
    render(
      <UnifiedPersonaWorkspace
        agentSlug="persona"
        activeSessionId="chat-1"
        sidebarRefreshTrigger={0}
        onSelectSession={vi.fn()}
        onSessionCreated={vi.fn()}
        onNewSession={vi.fn()}
      />,
    );

    await waitFor(() => {
      expect(screen.getByText("pause that task")).toBeInTheDocument();
    });

    expect(screen.getByText("Checked active work")).toBeInTheDocument();
    expect(screen.getByText("git-agent on agent-hub")).toBeInTheDocument();
    expect(screen.getByTestId("message-input")).toBeInTheDocument();
    expect(screen.getByTestId("session-dropdown")).toBeInTheDocument();
  });
});
