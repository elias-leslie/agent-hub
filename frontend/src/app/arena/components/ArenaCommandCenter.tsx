"use client";

import { useMemo, useState } from "react";
import { useQuery, useQueries } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  FlaskConical,
  Radar,
  Sparkles,
  Trophy,
} from "lucide-react";

import { fetchAgents, fetchAgentBenchmarkDashboard } from "@/lib/api";
import type { AgentBenchmarkDashboard } from "@/app/agents/[slug]/analytics/types";
import { deriveArenaStatus, formatPercent, formatScore } from "../utils";
import { ArenaAgentCard } from "./ArenaAgentCard";

type ArenaWindow = 7 | 30 | 90;

interface AggregateKPIs {
  totalRuns: number;
  avgScore: number | null;
  avgPassRate: number | null;
  totalRegressions: number;
}

function computeAggregate(dashboards: AgentBenchmarkDashboard[]): AggregateKPIs {
  if (dashboards.length === 0) {
    return { totalRuns: 0, avgScore: null, avgPassRate: null, totalRegressions: 0 };
  }

  let totalRuns = 0;
  let totalRegressions = 0;
  let scoreSum = 0;
  let scoreCount = 0;
  let passSum = 0;
  let passCount = 0;

  for (const d of dashboards) {
    totalRuns += d.overview.total_runs;
    totalRegressions += d.overview.open_regressions;
    if (d.overview.total_runs > 0) {
      scoreSum += d.overview.avg_score;
      scoreCount++;
      passSum += d.overview.pass_rate;
      passCount++;
    }
  }

  return {
    totalRuns,
    avgScore: scoreCount > 0 ? scoreSum / scoreCount : null,
    avgPassRate: passCount > 0 ? passSum / passCount : null,
    totalRegressions,
  };
}

function deriveSystemStatus(kpis: AggregateKPIs) {
  if (kpis.totalRegressions >= 5 || (kpis.avgPassRate !== null && kpis.avgPassRate < 60)) {
    return {
      label: "Regression pressure",
      tone: "bg-rose-950/30 text-rose-300 ring-1 ring-rose-800",
      detail: "Multiple agents are under active regression pressure. Prioritize the worst-first cards below.",
    };
  }
  if (kpis.totalRegressions > 0 || (kpis.avgScore !== null && kpis.avgScore < 90)) {
    return {
      label: "Under watch",
      tone: "bg-amber-950/30 text-amber-300 ring-1 ring-amber-800",
      detail: "System is mostly stable but some agents have open regressions or soft scores.",
    };
  }
  return {
    label: "Stable",
    tone: "bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800",
    detail: "All agents are holding steady with low regression pressure and solid benchmark scores.",
  };
}

function SkeletonCard() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
      <div className="flex items-center gap-3">
        <div className="h-4 w-4 rounded bg-slate-800 animate-shimmer" />
        <div className="h-4 w-32 rounded bg-slate-800 animate-shimmer" />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-3">
        <div className="h-8 rounded bg-slate-800/60 animate-shimmer" />
        <div className="h-8 rounded bg-slate-800/60 animate-shimmer" />
      </div>
      <div className="mt-3 h-3 w-24 rounded bg-slate-800/40 animate-shimmer" />
    </div>
  );
}

function SkeletonKPI() {
  return (
    <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm px-5 py-4">
      <div className="flex items-center gap-2">
        <div className="h-4 w-4 rounded bg-slate-800 animate-shimmer" />
        <div className="h-3 w-20 rounded bg-slate-800 animate-shimmer" />
      </div>
      <div className="mt-3 h-7 w-16 rounded bg-slate-800/60 animate-shimmer" />
    </div>
  );
}

export function ArenaCommandCenter() {
  const [windowDays, setWindowDays] = useState<ArenaWindow>(30);

  const {
    data: agentListData,
    isLoading: agentsLoading,
  } = useQuery({
    queryKey: ["agents-list"],
    queryFn: () => fetchAgents(true),
  });

  const agents = agentListData?.agents ?? [];

  const benchmarkQueries = useQueries({
    queries: agents.map((agent) => ({
      queryKey: ["agent-benchmarks", agent.slug, windowDays],
      queryFn: () => fetchAgentBenchmarkDashboard(agent.slug, windowDays, 24),
      enabled: agents.length > 0,
    })),
  });

  const allLoading = agentsLoading || benchmarkQueries.some((q) => q.isLoading);

  const dashboardMap = useMemo(() => {
    const map = new Map<string, AgentBenchmarkDashboard>();
    for (let i = 0; i < agents.length; i++) {
      const data = benchmarkQueries[i]?.data;
      if (data) {
        map.set(agents[i].slug, data);
      }
    }
    return map;
  }, [agents, benchmarkQueries]);

  const agentsWithData = useMemo(() => {
    return agents
      .filter((a) => dashboardMap.has(a.slug))
      .sort((a, b) => {
        const da = dashboardMap.get(a.slug)!;
        const db = dashboardMap.get(b.slug)!;
        const regDelta = db.overview.open_regressions - da.overview.open_regressions;
        if (regDelta !== 0) return regDelta;
        return (da.overview.avg_score ?? 999) - (db.overview.avg_score ?? 999);
      });
  }, [agents, dashboardMap]);

  const agentsWithoutData = useMemo(() => {
    return agents.filter((a) => !dashboardMap.has(a.slug));
  }, [agents, dashboardMap]);

  const aggregate = useMemo(() => {
    return computeAggregate(Array.from(dashboardMap.values()));
  }, [dashboardMap]);

  const systemStatus = useMemo(() => deriveSystemStatus(aggregate), [aggregate]);

  if (allLoading) {
    return (
      <div className="min-h-screen bg-slate-950">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
          <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3 lg:px-8">
            <div className="flex items-center gap-3">
              <FlaskConical className="h-5 w-5 text-amber-500" />
              <h1 className="text-lg font-bold tracking-tight text-slate-100">Arena</h1>
              <span className="rounded bg-amber-950/40 px-2 py-0.5 text-xs font-semibold text-amber-200 ring-1 ring-amber-900">
                Command Center
              </span>
            </div>
          </div>
        </header>
        <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
          <div className="rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 lg:p-8">
            <div className="h-5 w-48 rounded bg-slate-800 animate-shimmer" />
            <div className="mt-4 h-9 w-96 rounded bg-slate-800/60 animate-shimmer" />
            <div className="mt-3 h-4 w-80 rounded bg-slate-800/40 animate-shimmer" />
          </div>
          <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
            <SkeletonKPI />
            <SkeletonKPI />
            <SkeletonKPI />
            <SkeletonKPI />
          </div>
          <div className="mt-8">
            <div className="h-4 w-32 rounded bg-slate-800 animate-shimmer" />
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          </div>
        </main>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3 lg:px-8">
          <div className="flex items-center gap-3">
            <FlaskConical className="h-5 w-5 text-amber-500" />
            <h1 className="text-lg font-bold tracking-tight text-slate-100">
              Arena
            </h1>
            <span className="rounded bg-amber-950/40 px-2 py-0.5 text-xs font-semibold text-amber-200 ring-1 ring-amber-900">
              Command Center
            </span>
          </div>
          <select
            value={windowDays}
            onChange={(e) => setWindowDays(Number(e.target.value) as ArenaWindow)}
            className="rounded-lg border border-slate-700 bg-slate-800 px-3 py-1.5 text-xs font-medium text-slate-200 focus:outline-none focus:ring-2 focus:ring-amber-500/40"
          >
            <option value="7">Last 7 days</option>
            <option value="30">Last 30 days</option>
            <option value="90">Last 90 days</option>
          </select>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        {/* Hero section */}
        <section className="relative overflow-hidden rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm lg:p-8">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.08),transparent_38%),radial-gradient(circle_at_bottom_right,oklch(0.7_0.17_155_/_0.06),transparent_34%)]" />

          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-950/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-amber-200">
                <FlaskConical className="h-3.5 w-3.5" />
                Arena Command Center
              </div>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight text-slate-50 lg:text-4xl">
                Cross-agent benchmark health at a glance.
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                Aggregate stability, regressions, and score trends across every agent in the system.
                Drill into any agent for the full Arena field report.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <span
                  className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${systemStatus.tone}`}
                >
                  <Radar className="h-3.5 w-3.5" />
                  {systemStatus.label}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Activity className="h-3.5 w-3.5" />
                  {agentsWithData.length} agents reporting
                </span>
              </div>
            </div>

            <div className="relative grid gap-3 rounded-2xl border border-slate-800 bg-slate-950/60 p-4 xl:w-[360px]">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <p className="text-xs font-semibold uppercase tracking-[0.18em] text-slate-400">
                    System status
                  </p>
                  <p className="mt-2 text-sm text-slate-200">
                    {systemStatus.detail}
                  </p>
                </div>
                <Sparkles className="h-5 w-5 text-amber-500" />
              </div>
            </div>
          </div>
        </section>

        {/* Aggregate KPIs */}
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm px-5 py-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
              <FlaskConical className="h-4 w-4 text-blue-500" />
              Total Runs
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-50">
              {aggregate.totalRuns}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm px-5 py-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
              <Trophy className="h-4 w-4 text-emerald-500" />
              System Avg Score
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-50">
              {formatScore(aggregate.avgScore)}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm px-5 py-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
              <Activity className="h-4 w-4 text-amber-500" />
              System Pass Rate
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-50">
              {formatPercent(aggregate.avgPassRate)}
            </p>
          </div>
          <div className="rounded-2xl border border-slate-800 bg-slate-900/60 backdrop-blur-sm px-5 py-4">
            <div className="flex items-center gap-2 text-xs uppercase tracking-wide text-slate-400">
              <AlertTriangle className="h-4 w-4 text-rose-500" />
              Total Regressions
            </div>
            <p className="mt-2 text-2xl font-semibold text-slate-50">
              {aggregate.totalRegressions}
            </p>
          </div>
        </div>

        {/* Agent card grid */}
        {agentsWithData.length > 0 && (
          <div className="mt-8">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">
              Agents — worst-first
            </h3>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {agentsWithData.map((agent) => (
                <ArenaAgentCard
                  key={agent.slug}
                  agentName={agent.name}
                  slug={agent.slug}
                  dashboard={dashboardMap.get(agent.slug)!}
                />
              ))}
            </div>
          </div>
        )}

        {/* Agents without data */}
        {agentsWithoutData.length > 0 && (
          <div className="mt-8">
            <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-400">
              Awaiting benchmark data
            </h3>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {agentsWithoutData.map((agent) => (
                <div
                  key={agent.slug}
                  className="rounded-2xl border border-dashed border-slate-700 bg-slate-900/60 p-5"
                >
                  <div className="flex items-center gap-2">
                    <FlaskConical className="h-4 w-4 text-slate-500" />
                    <h4 className="text-sm font-semibold text-slate-300">
                      {agent.name}
                    </h4>
                  </div>
                  <p className="mt-2 text-xs text-slate-400">
                    No benchmark history yet. Run a benchmark battery to populate Arena data.
                  </p>
                </div>
              ))}
            </div>
          </div>
        )}

        {agents.length === 0 && !agentsLoading && (
          <div className="mt-12 text-center">
            <FlaskConical className="mx-auto h-10 w-10 text-slate-600" />
            <p className="mt-3 text-sm text-slate-400">
              No agents found. Create an agent to start building Arena benchmark history.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
