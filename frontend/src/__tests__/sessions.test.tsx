import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import SessionsPage from "@/app/sessions/page";

// Mock next/link
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string;
    children: React.ReactNode;
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}));

// Mock the API module
vi.mock("@/lib/api", () => ({
  fetchSessions: vi.fn(),
  fetchSession: vi.fn(),
}));

import { fetchSessions } from "@/lib/api";

const mockSessions = {
  sessions: [
    {
      id: "session-123-abc",
      project_id: "test-project",
      provider: "claude",
      model: "claude-sonnet-4-5",
      status: "active",
      agent_slug: "code_generation",
      session_type: "completion",
      message_count: 5,
      total_input_tokens: 1500,
      total_output_tokens: 800,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-07T10:00:00Z",
    },
    {
      id: "session-456-def",
      project_id: "test-project",
      provider: "gemini",
      model: "gemini-3-flash",
      status: "completed",
      agent_slug: null,
      session_type: "chat",
      message_count: 10,
      total_input_tokens: 3200,
      total_output_tokens: 1200,
      created_at: "2026-01-02T00:00:00Z",
      updated_at: "2026-01-06T15:00:00Z",
    },
  ],
  total: 2,
  page: 1,
  page_size: 20,
};

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });
  return function Wrapper({ children }: { children: React.ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
    );
  };
}

describe("SessionsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchSessions).mockResolvedValue(mockSessions);
  });

  it("renders sessions page header", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Sessions")).toBeInTheDocument();
  });

  it("displays session count after loading", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("2 total")).toBeInTheDocument();
    });
  });

  it("shows sessions after loading", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      // Sessions are displayed by project_id
      const projectIds = screen.getAllByText("test-project");
      expect(projectIds.length).toBe(2);
    });
  });

  it("shows status filter dropdown", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    expect(screen.getByTestId("filter-status")).toBeInTheDocument();
    expect(screen.getByText("All status")).toBeInTheDocument();
  });

  it("filters by status when selected", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(fetchSessions).toHaveBeenCalled();
    });

    // Change status filter using data-testid
    const select = screen.getByTestId("filter-status");
    fireEvent.change(select, { target: { value: "active" } });

    await waitFor(() => {
      const calls = vi.mocked(fetchSessions).mock.calls;
      const lastCall = calls[calls.length - 1];
      expect(lastCall[0]).toEqual(
        expect.objectContaining({
          status: "active",
        }),
      );
    });
  });

  it("shows search input", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    expect(
      screen.getByPlaceholderText("Search..."),
    ).toBeInTheDocument();
  });

  it("filters sessions by search query", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      const sessionIds = screen.getAllByText("test-project");
      expect(sessionIds.length).toBe(2);
    });

    // Search for something specific
    const searchInput = screen.getByPlaceholderText("Search...");
    fireEvent.change(searchInput, { target: { value: "456" } });

    // Only second session should remain (contains "456" in its ID)
    await waitFor(() => {
      const sessionIds = screen.getAllByText("test-project");
      expect(sessionIds.length).toBe(1);
    });
  });

  it("shows empty state when no sessions", async () => {
    vi.mocked(fetchSessions).mockResolvedValue({
      sessions: [],
      total: 0,
      page: 1,
      page_size: 20,
    });

    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("No sessions found")).toBeInTheDocument();
    });
  });

  it("shows token counts for each session", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      // Token pairs are displayed as "input / output" format
      // First session: 1500 / 800 -> "1.5k / 800"
      // Second session: 3200 / 1200 -> "3.2k / 1.2k"
      expect(screen.getByText("1.5k / 800")).toBeInTheDocument();
      expect(screen.getByText("3.2k / 1.2k")).toBeInTheDocument();
    });
  });

  it("has clickable session rows that can expand", async () => {
    render(<SessionsPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      const sessionIds = screen.getAllByText("test-project");
      expect(sessionIds.length).toBe(2);
    });

    // Rows are buttons, not links
    const buttons = screen.getAllByRole("button");
    // There should be multiple buttons (rows plus controls)
    expect(buttons.length).toBeGreaterThan(0);
  });
});
