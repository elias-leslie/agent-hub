"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { DollarSign, Clock, AlertTriangle, Zap, Loader2, AlertCircle } from "lucide-react";
import { fetchAgent, fetchAgentMetrics } from "./api";
import { metricsToAnalytics } from "./utils";
import { KPICard } from "./components/KPICard";
import { ChartCard } from "./components/ChartCard";
import { AnalyticsHeader } from "./components/AnalyticsHeader";
import { FailuresTable } from "./components/FailuresTable";
import { ChartSection } from "./components/ChartSection";

export default function AgentAnalyticsPage() {
  const params = useParams();
  const slug = params.slug as string;
  const [timeRange, setTimeRange] = useState("7d");

  const {
    data: agent,
    isLoading: agentLoading,
    error: agentError,
  } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  });

  const {
    data: metrics,
    isLoading: metricsLoading,
    error: metricsError,
  } = useQuery({
    queryKey: ["agent-metrics", slug],
    queryFn: () => fetchAgentMetrics(slug),
    enabled: !!slug,
  });

  const isLoading = agentLoading || metricsLoading;
  const error = agentError || metricsError;
  const analytics = agent && metrics ? metricsToAnalytics(metrics, agent) : null;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !agent || !analytics) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Agent not found
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <AnalyticsHeader
        agentName={agent.name}
        slug={slug}
        timeRange={timeRange}
        onTimeRangeChange={setTimeRange}
      />

      <main className="p-6 lg:p-8 max-w-7xl mx-auto">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
          <KPICard
            label="Total Cost"
            value={`$${analytics.total_cost_usd.toFixed(2)}`}
            icon={DollarSign}
            trend={analytics.trend.cost_change}
            color="blue"
          />
          <KPICard
            label="Avg Latency"
            value={analytics.avg_latency_ms}
            unit="ms"
            icon={Clock}
            trend={analytics.trend.latency_change}
            color="amber"
          />
          <KPICard
            label="Error Rate"
            value={`${analytics.error_rate}%`}
            icon={AlertTriangle}
            trend={analytics.trend.error_change}
            color="red"
          />
          <KPICard
            label="Cache Hit Rate"
            value={`${analytics.cache_hit_rate}%`}
            icon={Zap}
            color="green"
          />
        </div>

        <ChartSection analytics={analytics} />

        <ChartCard title="Recent Failures">
          <FailuresTable failures={analytics.recent_failures} />
        </ChartCard>

        <p className="mt-6 text-center text-xs text-slate-400">
          Showing 24h metrics. Detailed histograms and trends coming soon.
        </p>
      </main>
    </div>
  );
}
