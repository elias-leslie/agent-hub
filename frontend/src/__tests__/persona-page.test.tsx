import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
const mockToastSuccess = vi.fn();
const mockToastWarning = vi.fn();

const mockHeartbeatState = {
  status: {
    running: false,
    last_run: "2026-03-09T12:00:00Z",
  },
  isTriggering: false,
};

type MockPrimarySession =
  | {
      id: string;
      updated_at: string;
      live_activity: {
        phase: string;
        summary: string;
        current_tool_name: string;
        files_touched: string[];
      };
    }
  | null;

const mockRuntimeState: {
  primarySession: MockPrimarySession;
  activePersonaSessions: Array<{ id: string; status?: string; live_activity?: { status?: string; phase?: string } }>;
  activeChildSessions: Array<{ id: string; status?: string; live_activity?: { status?: string; phase?: string } }>;
  loading: boolean;
  error: string | null;
  stoppingSessionId: string | null;
  runtimeSyncKey: string;
  refresh: ReturnType<typeof vi.fn>;
  stopCurrentStream: typeof mockStopCurrentStream;
  stopActiveWork: typeof mockStopActiveWork;
} = {
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
  activePersonaSessions: [{ id: "hb-1", status: "active", live_activity: { status: "active", phase: "running_tool" } }],
  activeChildSessions: [{ id: "child-1", status: "active", live_activity: { status: "active", phase: "waiting_for_model" } }],
  loading: false,
  error: null,
  stoppingSessionId: null,
  runtimeSyncKey: "",
  refresh: vi.fn(),
  stopCurrentStream: mockStopCurrentStream,
  stopActiveWork: mockStopActiveWork,
};

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: vi.fn().mockReturnValue(null),
  }),
}));

vi.mock("@/components/error/toast", () => ({
  useToastActions: () => ({
    success: mockToastSuccess,
    warning: mockToastWarning,
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
      name: "Avery",
      agent_slug: "persona",
      heartbeat_interval_minutes: 60,
      execution_state: "active",
    },
    loading: false,
    error: null,
    updatePersona: mockUpdatePersona,
    autosave: {
      status: "idle",
      errorMessage: null,
      savedAt: null,
    },
  }),
}));

vi.mock("@/app/persona/hooks/useHeartbeat", () => ({
  useHeartbeat: () => ({
    status: mockHeartbeatState.status,
    trigger: mockTriggerHeartbeat,
    isTriggering: mockHeartbeatState.isTriggering,
  }),
}));

vi.mock("@/app/persona/hooks/usePersonaRuntime", () => ({
  usePersonaRuntime: () => mockRuntimeState,
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
    mockHeartbeatState.status = {
      running: false,
      last_run: "2026-03-09T12:00:00Z",
    };
    mockHeartbeatState.isTriggering = false;
    mockRuntimeState.primarySession = {
      id: "hb-1",
      updated_at: "2026-03-09T12:01:00Z",
      live_activity: {
        phase: "running_tool",
        summary: "Running validation",
        current_tool_name: "dt -q -d",
        files_touched: ["frontend/src/app/persona/page.tsx"],
      },
    };
    mockRuntimeState.activePersonaSessions = [{ id: "hb-1", status: "active", live_activity: { status: "active", phase: "running_tool" } }];
    mockRuntimeState.activeChildSessions = [{ id: "child-1", status: "active", live_activity: { status: "active", phase: "waiting_for_model" } }];
    mockRuntimeState.stoppingSessionId = null;
  });

  it("renders a compact operator header with the focused summary and core controls", () => {
    render(<PersonaPage />);

    expect(screen.getByTestId("unified-workspace")).toHaveTextContent("workspace:sess-123");
    expect(screen.getByText("Running validation")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Stop$/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Pause$/i })).toBeInTheDocument();
  });

  it("pauses the persona and stops focused live work when a runtime session exists", async () => {
    mockStopCurrentStream.mockResolvedValueOnce(true);

    render(<PersonaPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Pause$/i }));

    await waitFor(() => {
      expect(mockUpdatePersona).toHaveBeenCalledWith({
        execution_state: "paused",
      });
      expect(mockStopCurrentStream).toHaveBeenCalledTimes(1);
    });

    expect(mockToastSuccess).not.toHaveBeenCalled();
  });

  it("triggers a manual check-in and selects the dispatched session when idle", async () => {
    mockRuntimeState.primarySession = null;
    mockRuntimeState.activePersonaSessions = [];
    mockRuntimeState.activeChildSessions = [];
    mockTriggerHeartbeat.mockResolvedValueOnce("hb-idle-1");

    render(<PersonaPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Check now$/i }));

    expect(mockTriggerHeartbeat).toHaveBeenCalledTimes(1);
    await waitFor(() => {
      expect(mockHandleSelectSession).toHaveBeenCalledWith("hb-idle-1");
    });
  });

  it("stops only focused live work from the compact header", async () => {
    mockStopCurrentStream.mockResolvedValueOnce(true);

    render(<PersonaPage />);

    fireEvent.click(screen.getByRole("button", { name: /^Stop$/i }));

    await waitFor(() => {
      expect(mockStopCurrentStream).toHaveBeenCalledTimes(1);
      expect(mockToastSuccess).toHaveBeenCalledWith("Stopped live work for Avery");
    });
    expect(mockStopActiveWork).not.toHaveBeenCalled();
  });
});
