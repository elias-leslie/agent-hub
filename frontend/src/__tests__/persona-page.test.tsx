import { render, screen, fireEvent } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import PersonaPage from "@/app/persona/page";

const mockUpdatePersona = vi.fn();
const mockTriggerHeartbeat = vi.fn();
const mockHandleSelectSession = vi.fn();
const mockHandleNewSession = vi.fn();
const mockHandleSessionCreated = vi.fn();
const mockStopCurrentStream = vi.fn();
const mockStopActiveWork = vi.fn();

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: vi.fn().mockReturnValue(null),
  }),
}));

vi.mock("@/components/error/toast", () => ({
  useToastActions: () => ({
    success: vi.fn(),
    warning: vi.fn(),
    error: vi.fn(),
  }),
}));

vi.mock("next/link", () => ({
  default: ({
    children,
    href,
    ...rest
  }: {
    children: ReactNode;
    href: string;
    [key: string]: unknown;
  }) => (
    <a href={href} {...rest}>{children}</a>
  ),
}));

vi.mock("@/app/persona/components/UnifiedPersonaWorkspace", () => ({
  UnifiedPersonaWorkspace: ({ activeSessionId }: { activeSessionId: string | null }) => (
    <div data-testid="unified-workspace">workspace:{activeSessionId ?? "new"}</div>
  ),
}));

vi.mock("@/app/persona/hooks/usePersona", () => ({
  usePersona: () => ({
    persona: {
      name: "Jenny",
      agent_slug: "persona",
      heartbeat_interval_minutes: 60,
      execution_state: "active",
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

vi.mock("@/app/persona/hooks/usePersonaRuntime", () => ({
  usePersonaRuntime: () => ({
    primarySession: {
      id: "hb-1",
      updated_at: "2026-03-09T12:01:00Z",
      live_activity: {
        phase: "running_tool",
        summary: "Running validation",
        current_tool_name: "dt -q -d",
        files_touched: ["frontend/src/app/persona/page.tsx"],
      },
    },
    activePersonaSessions: [{ id: "hb-1" }],
    activeChildSessions: [{ id: "child-1" }],
    loading: false,
    error: null,
    stoppingSessionId: null,
    runtimeSyncKey: "",
    refresh: vi.fn(),
    stopCurrentStream: mockStopCurrentStream,
    stopActiveWork: mockStopActiveWork,
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

  it("renders the unified workspace", async () => {
    render(<PersonaPage />);

    expect(await screen.findByText("Unified workspace")).toBeInTheDocument();
    expect(screen.getByTestId("unified-workspace")).toHaveTextContent("workspace:sess-123");
    expect(screen.getByText("Running validation")).toBeInTheDocument();
    expect(screen.getByText("dt -q -d")).toBeInTheDocument();
  });

  it("pauses Jenny from the main workspace header", async () => {
    render(<PersonaPage />);

    fireEvent.click(await screen.findByText("Pause Jenny"));

    expect(mockUpdatePersona).toHaveBeenCalledWith({
      execution_state: "paused",
    });
    expect(mockStopCurrentStream).toHaveBeenCalledTimes(1);
  });

  it("triggers a manual heartbeat from the main workspace header", async () => {
    render(<PersonaPage />);

    fireEvent.click(await screen.findByText("Heartbeat"));

    expect(mockTriggerHeartbeat).toHaveBeenCalledTimes(1);
  });

  it("starts a new thread from the runtime controls", async () => {
    render(<PersonaPage />);

    fireEvent.click(await screen.findByText("New thread"));

    expect(mockHandleNewSession).toHaveBeenCalledTimes(1);
  });

  it("exposes Jenny analytics from the workspace header", async () => {
    render(<PersonaPage />);

    const analyticsLink = await screen.findByTitle("Jenny analytics");
    expect(analyticsLink).toHaveAttribute("href", "/persona/analytics");
  });
});
