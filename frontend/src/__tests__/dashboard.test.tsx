import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import DashboardPage from "@/app/dashboard/page";

// Mock the API module
vi.mock("@/lib/api", () => ({
  fetchStatus: vi.fn(),
  fetchCosts: vi.fn(),
}));

import { fetchStatus, fetchCosts } from "@/lib/api";

const mockStatus = {
  status: "healthy" as const,
  service: "agent-hub",
  database: "connected",
  providers: [
    {
      name: "claude",
      available: true,
      configured: true,
      error: null,
      health: {
        state: "healthy" as const,
        latency_ms: 150,
        error_rate: 0.01,
        availability: 0.99,
        consecutive_failures: 0,
        last_check: Date.now() / 1000,
        last_success: Date.now() / 1000,
        last_error: null,
      },
    },
    {
      name: "gemini",
      available: true,
      configured: true,
      error: null,
      health: {
        state: "healthy" as const,
        latency_ms: 200,
        error_rate: 0.02,
        availability: 0.98,
        consecutive_failures: 0,
        last_check: Date.now() / 1000,
        last_success: Date.now() / 1000,
        last_error: null,
      },
    },
  ],
  uptime_seconds: 3600,
};

const mockDailyCosts = {
  aggregations: [
    {
      group_key: "2026-01-01",
      total_tokens: 1000,
      input_tokens: 600,
      output_tokens: 400,
      total_cost_usd: 0.01,
      request_count: 5,
    },
    {
      group_key: "2026-01-02",
      total_tokens: 2000,
      input_tokens: 1200,
      output_tokens: 800,
      total_cost_usd: 0.02,
      request_count: 10,
    },
  ],
  total_cost_usd: 0.03,
  total_tokens: 3000,
  total_requests: 15,
};

const mockModelCosts = {
  aggregations: [
    {
      group_key: "claude-sonnet-4-5",
      total_tokens: 2000,
      input_tokens: 1200,
      output_tokens: 800,
      total_cost_usd: 0.02,
      request_count: 10,
    },
    {
      group_key: "gemini-flash",
      total_tokens: 1000,
      input_tokens: 600,
      output_tokens: 400,
      total_cost_usd: 0.01,
      request_count: 5,
    },
  ],
  total_cost_usd: 0.03,
  total_tokens: 3000,
  total_requests: 15,
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

describe("DashboardPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(fetchStatus).mockResolvedValue(mockStatus);
    vi.mocked(fetchCosts).mockImplementation((params) => {
      if (params.group_by === "day") return Promise.resolve(mockDailyCosts);
      if (params.group_by === "model") return Promise.resolve(mockModelCosts);
      return Promise.resolve(mockDailyCosts);
    });
  });

  it("renders dashboard header", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Agent Hub")).toBeInTheDocument();
    expect(screen.getByText("Monitoring Dashboard")).toBeInTheDocument();
  });

  it("displays KPI cards", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    expect(screen.getByText("Active Sessions")).toBeInTheDocument();
    expect(screen.getByText("Total Cost")).toBeInTheDocument();
    expect(screen.getByText("Requests")).toBeInTheDocument();
    expect(screen.getByText("Error Rate")).toBeInTheDocument();
  });

  it("shows provider status after loading", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("claude")).toBeInTheDocument();
      expect(screen.getByText("gemini")).toBeInTheDocument();
    });
  });

  it("displays healthy status indicator", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText("healthy")).toBeInTheDocument();
    });
  });

  it("shows uptime after loading", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(screen.getByText(/1h 0m uptime/)).toBeInTheDocument();
    });
  });

  it("displays cost data after loading", async () => {
    render(<DashboardPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      // Check that cost is displayed (formatted as currency) - multiple cost values shown
      const costElements = screen.getAllByText(/\$0\.0/);
      expect(costElements.length).toBeGreaterThan(0);
    });
  });

  it("handles API error gracefully", async () => {
    vi.mocked(fetchStatus).mockRejectedValue(new Error("Network error"));

    render(<DashboardPage />, { wrapper: createWrapper() });

    await waitFor(() => {
      expect(
        screen.getByText(/Failed to load dashboard data/),
      ).toBeInTheDocument();
    });
  });
});
