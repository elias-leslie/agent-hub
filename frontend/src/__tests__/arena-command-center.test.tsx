import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ArenaCommandCenter } from "@/app/arena/components/ArenaCommandCenter";

vi.mock("@/lib/api", () => ({
  fetchArenaOverview: vi.fn(),
}));

import { fetchArenaOverview } from "@/lib/api";

function renderCommandCenter() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ArenaCommandCenter />
    </QueryClientProvider>,
  );
}

describe("ArenaCommandCenter", () => {
  it("shows autonomy and memory pulse from the overview payload", async () => {
    vi.mocked(fetchArenaOverview).mockResolvedValue({
      generated_at: "2026-03-22T15:30:00Z",
      project_id: "agent-hub",
      primary_agent_slug: "persona",
      days: 30,
      system: {
        total_agents: 2,
        agents_with_history: 1,
        total_runs: 12,
        avg_score: 91.2,
        avg_pass_rate: 77,
        total_regressions: 3,
        regressions_by_category: { behavior: 3 },
      },
      scheduled_jobs: [
        {
          id: "job-review",
          name: "Daily Jenny Improvement Review",
          payload_type: "agent_turn",
          enabled: true,
          last_run_at: null,
          next_run_at: "2026-03-23T09:00:00Z",
          run_count: 0,
        },
        {
          id: "job-honing",
          name: "Nightly Jenny Self-Honing",
          payload_type: "self_honing",
          enabled: true,
          last_run_at: null,
          next_run_at: "2026-03-23T09:30:00Z",
          run_count: 0,
        },
      ],
      agent_signal_volume: [
        {
          agent_slug: "persona",
          friction: 2,
          improvement: 1,
          idea: 0,
          praise: 0,
          system: 2,
        },
      ],
      repeated_issues: [
        {
          agent_slug: "persona",
          feedback_type: "friction",
          content: "missed rebuild.sh before verification",
          count: 2,
          latest_at: "2026-03-22T15:00:00Z",
        },
      ],
      recent_benchmark_experiments: [
        {
          suite_id: "persona-suite",
          decision: "hold",
          decision_reason: "underpowered",
          score_delta: -0.5,
          pass_rate_delta: 0,
        },
      ],
      open_regression_clusters: [
        {
          case_id: "rebuild_rule_reconsideration",
          occurrence_count: 3,
          failure_detail: "forgot rebuild.sh",
          failure_kind: "model",
          failure_category: "behavior",
          last_seen_at: "2026-03-22T15:00:00Z",
        },
      ],
      memory_utilization: {
        injection_sessions: 4,
        citation_sessions: 2,
        lookup_after_injection_sessions: 2,
        citation_session_rate: 0.5,
        assistant_citation_rate: 0.5,
        selected_reference_citation_rate: 0.333,
        memory_search_calls: 5,
        memory_get_calls: 1,
        memory_debug_coverage_rate: 1,
      },
      low_yield_references: [
        {
          uuid: "ref-2",
          label: "noisy-ref",
          selected: 2,
          cited: 0,
          citation_rate: 0,
          tags: ["debugger-relevant"],
        },
      ],
      agents: [
        {
          slug: "persona",
          name: "Jenny",
          description: "Primary persona",
          benchmark: {
            total_runs: 12,
            avg_score: 91.2,
            pass_rate: 77,
            open_regressions: 3,
            latest_completed_at: "2026-03-22T12:00:00Z",
          },
          signal_volume: {
            agent_slug: "persona",
            friction: 2,
            improvement: 1,
            idea: 0,
            praise: 0,
            system: 2,
          },
          top_issue: {
            agent_slug: "persona",
            feedback_type: "friction",
            content: "missed rebuild.sh before verification",
            count: 2,
            latest_at: "2026-03-22T15:00:00Z",
          },
        },
        {
          slug: "debugger",
          name: "Debugger",
          description: "Debug specialist",
          benchmark: {
            total_runs: 0,
            avg_score: null,
            pass_rate: null,
            open_regressions: 0,
            latest_completed_at: null,
          },
          signal_volume: null,
          top_issue: null,
        },
      ],
    });

    renderCommandCenter();

    await waitFor(() => {
      expect(screen.getByText("Jenny + Agent Pulse")).toBeInTheDocument();
    });

    expect(screen.getByText("Daily review")).toBeInTheDocument();
    expect(screen.getByText("Nightly honing")).toBeInTheDocument();
    expect(screen.getByText("Memory health")).toBeInTheDocument();
    expect(screen.getByText("Benchmark coverage")).toBeInTheDocument();
    expect(screen.getByText("Open decision regressions")).toBeInTheDocument();
    expect(screen.getByText("Read This First")).toBeInTheDocument();
    expect(screen.getAllByText("behavior")).toHaveLength(1);
    expect(screen.getAllByText("missed rebuild.sh before verification")).toHaveLength(2);
    expect(screen.getByText("noisy-ref")).toBeInTheDocument();
    expect(screen.getByText("Jenny")).toBeInTheDocument();
    expect(screen.getByText("Debugger")).toBeInTheDocument();
  });
});
