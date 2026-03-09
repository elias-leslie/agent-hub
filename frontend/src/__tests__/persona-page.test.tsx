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
  default: ({ children, href }: { children: unknown; href: string }) => (
    <a href={href}>{children as string}</a>
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

  it("renders the unified workspace", async () => {
    render(<PersonaPage />);

    expect(await screen.findByText("Unified workspace")).toBeInTheDocument();
    expect(screen.getByTestId("unified-workspace")).toHaveTextContent("workspace:sess-123");
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
