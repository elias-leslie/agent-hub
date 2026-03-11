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
  fetchAgentBenchmarkDashboard: vi.fn(),
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

vi.mock("@/app/agents/[slug]/analytics/components/BenchmarkTrendSection", () => ({
  BenchmarkTrendSection: () => <div>benchmark trend section</div>,
}));

import { fetchAgent, fetchAgentBenchmarkDashboard, fetchAgentMetrics } from "@/lib/api";

const agent: Agent = {
  id: 1,
  slug: "persona",
  name: "Persona",
  description: "Primary persona",
  system_prompt: "You are Persona.",
  primary_model_id: "claude-sonnet-4-5",
  fallback_models: [],
  escalation_model_id: null,
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
    vi.mocked(fetchAgentBenchmarkDashboard).mockResolvedValue({
      agent_slug: "persona",
      overview: {
        total_runs: 0,
        avg_score: 0,
        pass_rate: 0,
        open_regressions: 0,
        latest_completed_at: null,
        tracked_models: [],
      },
      trend: [],
      recent_runs: [],
      open_regressions: [],
      model_performance: [],
    });
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
    expect(screen.getByText("No persisted benchmark runs yet")).toBeInTheDocument();
  });

  it("renders benchmark observability data when persisted history exists", async () => {
    vi.mocked(fetchAgent).mockResolvedValue(agent);
    vi.mocked(fetchAgentMetrics).mockResolvedValue({
      slug: "persona",
      requests_24h: 4,
      avg_latency_ms: 200,
      success_rate: 100,
      tokens_24h: 4000,
      cost_24h_usd: 0.2,
      latency_trend: Array.from({ length: 24 }, () => 200),
      success_trend: Array.from({ length: 24 }, () => 100),
    });
    vi.mocked(fetchAgentBenchmarkDashboard).mockResolvedValue({
      agent_slug: "persona",
      overview: {
        total_runs: 3,
        avg_score: 94.2,
        pass_rate: 75,
        open_regressions: 1,
        latest_completed_at: "2026-03-11T12:00:00Z",
        tracked_models: ["codex/gpt-5.4"],
      },
      trend: [
        {
          run_id: "run-1",
          completed_at: new Date().toISOString(),
          suite_id: "jenny-patience",
          run_kind: "benchmark",
          avg_score: 94.2,
          pass_rate: 75,
          attempts: 12,
          prompt_version: null,
        },
      ],
      recent_runs: [
        {
          run_id: "run-1",
          benchmark_id: "jenny-benchmark-aaaa1111",
          suite_id: "jenny-patience",
          run_kind: "benchmark",
          started_at: "2026-03-11T11:00:00Z",
          completed_at: "2026-03-11T12:00:00Z",
          avg_score: 94.2,
          pass_rate: 75,
          attempt_count: 12,
          passed_attempt_count: 9,
          infra_failure_count: 0,
          models: ["codex/gpt-5.4"],
          case_ids: ["session_patience_quiet"],
          config_snapshot: {},
          metadata: {},
        },
      ],
      open_regressions: [
        {
          regression_key: "session_patience_quiet::wrong_fields: should_dispatch",
          suite_id: "jenny-patience",
          case_id: "session_patience_quiet",
          failure_detail: "wrong_fields: should_dispatch",
          status: "open",
          occurrence_count: 2,
          latest_avg_score: 78.8,
          affected_models: ["codex/gpt-5.4"],
          opened_at: "2026-03-11T10:00:00Z",
          last_seen_at: "2026-03-11T12:00:00Z",
          resolved_at: null,
        },
      ],
      model_performance: [
        {
          model_id: "codex/gpt-5.4",
          attempts: 12,
          avg_score: 94.2,
          pass_rate: 75,
          avg_latency_ms: 1100,
          latest_completed_at: "2026-03-11T12:00:00Z",
        },
      ],
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByText("benchmark trend section")).toBeInTheDocument();
    });

    expect(screen.getAllByText("Open Regressions")).toHaveLength(2);
    expect(screen.getByText("session_patience_quiet")).toBeInTheDocument();
    expect(screen.getByText("Benchmark Model Performance")).toBeInTheDocument();
  });
});
