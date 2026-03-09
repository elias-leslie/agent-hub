import type { ReactNode } from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PersonaPage from "@/app/persona/page";

const mockUpdatePersona = vi.fn();
const mockTriggerHeartbeat = vi.fn();
const mockHandleSelectSession = vi.fn();
const mockHandleNewSession = vi.fn();
const mockHandleSessionCreated = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: vi.fn().mockReturnValue(null),
  }),
}));

vi.mock("next/link", () => ({
  default: ({ children, href }: { children: ReactNode; href: string }) => (
    <a href={href}>{children}</a>
  ),
}));

vi.mock("@/components/chat", () => ({
  ChatPanel: ({ sessionId }: { sessionId?: string }) => (
    <div data-testid="chat-panel">chat:{sessionId ?? "new"}</div>
  ),
}));

vi.mock("@/components/chat/session-dropdown", () => ({
  SessionDropdown: () => <div data-testid="session-dropdown">sessions</div>,
}));

vi.mock("@/app/persona/components/ActivityTimeline", () => ({
  ActivityTimeline: ({ heartbeatRunning }: { heartbeatRunning?: boolean }) => (
    <div data-testid="activity-timeline">activity:{heartbeatRunning ? "running" : "idle"}</div>
  ),
}));

vi.mock("@/app/persona/hooks/usePersona", () => ({
  usePersona: () => ({
    persona: {
      name: "Jenny",
      agent_slug: "persona",
      heartbeat_interval_minutes: 60,
    },
    loading: false,
    error: null,
    updatePersona: mockUpdatePersona,
  }),
}));

vi.mock("@/app/persona/hooks/useHeartbeat", () => ({
  useHeartbeat: () => ({
    status: {
      running: false,
      last_run: "2026-03-09T12:00:00Z",
    },
    trigger: mockTriggerHeartbeat,
    isTriggering: false,
  }),
}));

vi.mock("@/app/chat/hooks/useChatSession", () => ({
  useChatSession: () => ({
    activeSessionId: "sess-123",
    sidebarRefreshTrigger: 0,
    handleSessionCreated: mockHandleSessionCreated,
    handleSelectSession: mockHandleSelectSession,
    handleNewSession: mockHandleNewSession,
  }),
}));

describe("PersonaPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders chat and activity together in one workspace", async () => {
    render(<PersonaPage />);

    expect(await screen.findByText("Unified workspace")).toBeInTheDocument();
    expect(screen.getByTestId("chat-panel")).toHaveTextContent("chat:sess-123");
    expect(screen.getByTestId("activity-timeline")).toHaveTextContent("activity:idle");
  });

  it("pauses auto-run from the main workspace header", async () => {
    render(<PersonaPage />);

    fireEvent.click(await screen.findByText("Pause auto-run"));

    expect(mockUpdatePersona).toHaveBeenCalledWith({
      heartbeat_interval_minutes: 0,
    });
  });

  it("triggers a manual heartbeat from the main workspace header", async () => {
    render(<PersonaPage />);

    fireEvent.click(await screen.findByText("Heartbeat"));

    expect(mockTriggerHeartbeat).toHaveBeenCalledTimes(1);
  });
});
