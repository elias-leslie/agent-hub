import { describe, expect, it } from "vitest";
import { metricsToAnalytics, sliceTrendWindow } from "@/app/agents/[slug]/analytics/utils";
import type {
  Agent,
  AgentMetrics,
} from "@/app/agents/[slug]/analytics/types";

const agent: Agent = {
  id: 1,
  slug: "persona",
  name: "Persona",
  primary_model_id: "claude-sonnet-4-5",
  fallback_models: ["gemini-2.5-flash"],
  premium_model_id: "codex/gpt-5.4",
  updated_at: "2026-03-06T14:00:00Z",
};

const metrics: AgentMetrics = {
  slug: "persona",
  requests_24h: 48,
  avg_latency_ms: 850,
  success_rate: 97.5,
  tokens_24h: 120000,
  cost_24h_usd: 4.25,
  latency_trend: Array.from({ length: 24 }, (_, index) => 500 + index * 10),
  success_trend: Array.from({ length: 24 }, (_, index) => 90 + (index % 5)),
};

describe("agent analytics utils", () => {
  it("maps backend metrics into honest analytics data", () => {
    const analytics = metricsToAnalytics(metrics, agent);

    expect(analytics.totalCostUsd).toBe(4.25);
    expect(analytics.errorRate).toBe(2.5);
    expect(analytics.requestsPerHour).toBe(2);
    expect(analytics.modelSummary).toEqual([
      "claude-sonnet-4-5",
      "gemini-2.5-flash",
      "codex/gpt-5.4",
    ]);
    expect(analytics.trend).toHaveLength(24);
  });

  it("slices the visible trend window from the end", () => {
    const analytics = metricsToAnalytics(metrics, agent);

    const window = sliceTrendWindow(analytics.trend, 6);

    expect(window).toHaveLength(6);
    expect(window[0]?.hour).toBe("18:00");
    expect(window[5]?.hour).toBe("23:00");
  });
});
