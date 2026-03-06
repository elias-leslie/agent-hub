import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import AgentAnalyticsPage from "@/app/agents/[slug]/analytics/page";
import type { Agent } from "@/app/agents/[slug]/types";

vi.mock("next/navigation", () => ({
  useParams: () => ({ slug: "persona" }),
  useRouter: () => ({
    push: vi.fn(),
  }),
}));

vi.mock("@/lib/api", () => ({
  fetchAgent: vi.fn(),
  fetchAgentMetrics: vi.fn(),
}));

vi.mock("@/app/agents/[slug]/analytics/components/AnalyticsHeader", () => ({
  AnalyticsHeader: ({ agentName }: { agentName: string }) => <div>{agentName} analytics</div>,
}));

vi.mock("@/app/agents/[slug]/analytics/components/KPICard", () => ({
  KPICard: ({ label, value }: { label: string; value: string | number }) => (
    <div>
      <span>{label}</span>
      <span>{String(value)}</span>
    </div>
  ),
}));

vi.mock("@/app/agents/[slug]/analytics/components/ChartCard", () => ({
  ChartCard: ({ title, children }: { title: string; children: React.ReactNode }) => (
    <section>
      <h2>{title}</h2>
      {children}
    </section>
  ),
}));

vi.mock("@/app/agents/[slug]/analytics/components/ChartSection", () => ({
  ChartSection: () => <div>chart section</div>,
}));

import { fetchAgent, fetchAgentMetrics } from "@/lib/api";

const agent: Agent = {
  id: 1,
  slug: "persona",
  name: "Persona",
  description: "Primary persona",
  system_prompt: "You are Persona.",
  primary_model_id: "claude-sonnet-4-5",
  fallback_models: [],
  escalation_model_id: null,
  premium_model_id: null,
  strategies: {},
  temperature: 0.2,
  thinking_level: "medium",
  verbosity_level: "medium",
  is_active: true,
  is_coding_agent: false,
  tool_permissions: null,
  memory_config: null,
  max_concurrency: null,
  max_subagent_concurrency: null,
  daily_token_budget: null,
  hourly_request_limit: null,
  timeout_seconds: 60,
  version: 1,
  created_at: "2026-03-06T13:00:00Z",
  updated_at: "2026-03-06T14:00:00Z",
};

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <AgentAnalyticsPage />
    </QueryClientProvider>,
  );
}

describe("AgentAnalyticsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows the fetch error instead of a misleading not-found message", async () => {
    vi.mocked(fetchAgent).mockResolvedValue(agent);
    vi.mocked(fetchAgentMetrics).mockRejectedValue(new Error("metrics offline"));

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("Failed to load analytics")).toBeInTheDocument();
    });

    expect(screen.getByText("metrics offline")).toBeInTheDocument();
    expect(screen.queryByText("Agent not found")).not.toBeInTheDocument();
  });

  it("shows a clear empty state when the agent has no recent activity", async () => {
    vi.mocked(fetchAgent).mockResolvedValue(agent);
    vi.mocked(fetchAgentMetrics).mockResolvedValue({
      slug: "persona",
      requests_24h: 0,
      avg_latency_ms: 0,
      success_rate: 0,
      tokens_24h: 0,
      cost_24h_usd: 0,
      latency_trend: [],
      success_trend: [],
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("No recent activity")).toBeInTheDocument();
    });

    expect(
      screen.getByText("This agent has not handled any requests in the last 24 hours yet."),
    ).toBeInTheDocument();
  });
});
