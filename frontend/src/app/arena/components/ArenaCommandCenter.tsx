"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Brain,
  CalendarClock,
  FlaskConical,
  Radar,
  Search,
  ShieldAlert,
  Sparkles,
  Target,
  Trophy,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { fetchArenaOverview } from "@/lib/api";
import type {
  ArenaAgentBenchmarkSummary,
  ArenaOverview,
  ArenaScheduledJobSummary,
} from "@/app/arena/types";
import {
  deriveArenaStatusFromBenchmark,
  formatPercent,
  formatRelativeTime,
  formatScore,
  summarizeArenaIssue,
} from "../utils";
import { usePersonaDisplayName } from "@/app/persona/hooks/usePersonaDisplayName";
import { ArenaAgentCard } from "./ArenaAgentCard";

type ArenaWindow = 7 | 30 | 90;

function formatDateTime(value: string | null | undefined) {
  if (!value) {
    return "Not scheduled";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "Unknown";
  }
  return date.toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function deriveMemoryGovernanceTone(status: string) {
  if (status === "critical") {
    return "bg-rose-950/30 text-rose-300 ring-1 ring-rose-800";
  }
  if (status === "warn") {
    return "bg-amber-950/30 text-amber-300 ring-1 ring-amber-800";
  }
  return "bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800";
}

function deriveSystemStatus(overview: ArenaOverview, personaName: string) {
  if (overview.system.total_regressions >= 8 || (overview.system.avg_pass_rate ?? 100) < 60) {
    return {
      label: "Regression pressure",
      tone: "bg-rose-950/30 text-rose-300 ring-1 ring-rose-800",
      detail: `${personaName} and the workforce have active failures worth triaging before confidence rises.`,
    };
  }
  if (
    overview.repeated_issues.length > 0
    || overview.low_yield_references.length > 0
    || overview.open_regression_clusters.length > 0
  ) {
    return {
      label: "Under watch",
      tone: "bg-amber-950/30 text-amber-300 ring-1 ring-amber-800",
      detail: "The loop is running, but there are still signal-quality or reliability gaps worth tightening.",
    };
  }
  return {
    label: "Stable",
    tone: "bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800",
    detail: "Autonomy, memory, and benchmark signals are currently aligned without obvious pressure spikes.",
  };
}

function derivePressureCount(agents: Array<{ benchmark: ArenaAgentBenchmarkSummary }>) {
  return agents.filter((agent) => {
    const label = deriveArenaStatusFromBenchmark(agent.benchmark).label;
    return label === "Regression pressure" || label === "Under watch";
  }).length;
}

function getScheduledJob(
  jobs: ArenaScheduledJobSummary[],
  matcher: (job: ArenaScheduledJobSummary) => boolean,
) {
  return jobs.find(matcher) ?? null;
}

function SkeletonCard({ className }: { className: string }) {
  return <div className={`rounded-xl bg-slate-800/70 animate-shimmer ${className}`} />;
}

function LoadingState() {
  return (
    <div className="page-shell">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="mx-auto flex max-w-7xl items-center justify-between px-6 py-3 lg:px-8">
          <div className="flex items-center gap-3">
            <FlaskConical className="h-5 w-5 text-amber-500" />
            <h1 className="text-lg font-bold tracking-tight text-slate-100">Arena</h1>
          </div>
        </div>
      </header>
      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <div className="rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 lg:p-8">
          <SkeletonCard className="h-5 w-44" />
          <SkeletonCard className="mt-4 h-10 w-[30rem]" />
          <SkeletonCard className="mt-3 h-4 w-[28rem]" />
        </div>
        <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }).map((_, index) => (
            <div key={index} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <SkeletonCard className="h-3 w-20" />
              <SkeletonCard className="mt-3 h-8 w-20" />
            </div>
          ))}
        </div>
        <div className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div key={index} className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <SkeletonCard className="h-4 w-32" />
              <SkeletonCard className="mt-4 h-16 w-full" />
            </div>
          ))}
        </div>
      </main>
    </div>
  );
}

export function ArenaCommandCenter() {
  const { personaName, personaPossessive } = usePersonaDisplayName();
  const [windowDays, setWindowDays] = useState<ArenaWindow>(30);

  const {
    data,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["arena-overview", windowDays],
    queryFn: () => fetchArenaOverview(windowDays),
  });

  const overview = data ?? null;
  const systemStatus = useMemo(
    () => (overview ? deriveSystemStatus(overview, personaName) : null),
    [overview, personaName],
  );
  const memoryGovernance = overview?.memory_governance ?? null;
  const pressuredAgents = useMemo(
    () => (overview ? derivePressureCount(overview.agents) : 0),
    [overview],
  );
  const coverageRate = useMemo(
    () => (overview && overview.system.total_agents > 0
      ? (overview.system.agents_with_history / overview.system.total_agents) * 100
      : 0),
    [overview],
  );
  const reviewJob = useMemo(
    () => (overview ? getScheduledJob(overview.scheduled_jobs, (job) => job.payload_type === "agent_turn") : null),
    [overview],
  );
  const honingJob = useMemo(
    () => (overview ? getScheduledJob(overview.scheduled_jobs, (job) => job.payload_type === "self_honing") : null),
    [overview],
  );

  if (isLoading) {
    return <LoadingState />;
  }

  if (error || !overview) {
    const message = error instanceof Error ? error.message : "Failed to load Arena";
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />
        <div className="relative max-w-md rounded-2xl border border-rose-900 bg-slate-900/90 p-8 text-center">
          <ShieldAlert className="mx-auto mb-3 h-10 w-10 text-rose-500" />
          <p className="text-sm font-semibold text-slate-100">Arena unavailable</p>
          <p className="mt-2 text-sm text-slate-400">{message}</p>
        </div>
      </div>
    );
  }

  return (
    <div className="page-shell">
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
          <div className="flex items-center rounded-lg border border-slate-700 bg-slate-800 p-0.5">
            {([7, 30, 90] as ArenaWindow[]).map((days) => (
              <button
                key={days}
                type="button"
                onClick={() => setWindowDays(days)}
                className={cn(
                  "px-3 py-1 text-xs font-medium rounded-md transition-all duration-150",
                  windowDays === days
                    ? "bg-amber-500 text-slate-950 shadow-sm"
                    : "text-slate-400 hover:text-slate-200"
                )}
              >
                {days}d
              </button>
            ))}
          </div>
        </div>
      </header>

      <main className="relative mx-auto max-w-7xl p-6 lg:p-8">
        <section className="relative overflow-hidden rounded-[20px] border border-slate-800 bg-slate-900/60 p-6 backdrop-blur-sm lg:p-8">
          <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.08),transparent_38%),radial-gradient(circle_at_bottom_right,oklch(0.7_0.17_155_/_0.06),transparent_34%)]" />

          <div className="relative flex flex-col gap-6 xl:flex-row xl:items-end xl:justify-between">
            <div className="max-w-3xl">
              <div className="inline-flex items-center gap-2 rounded-full bg-amber-950/60 px-3 py-1 text-xs font-semibold uppercase tracking-[0.18em] text-amber-200">
                <Sparkles className="h-3.5 w-3.5" />
                {personaName} + Agent Pulse
              </div>
              <h2 className="mt-4 text-3xl font-semibold tracking-tight lg:text-4xl">
                <span className="gradient-text-amber">See autonomy, memory, and benchmark</span>
                <br />
                <span className="text-slate-50">pressure in one place.</span>
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-300">
                Arena now tracks the operational loop itself: scheduled review, scheduled honing,
                memory signal quality, and the agents currently producing the most pressure.
              </p>

              <div className="mt-5 flex flex-wrap gap-2">
                <span className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold ${systemStatus?.tone ?? ""}`}>
                  <Radar className="h-3.5 w-3.5" />
                  {systemStatus?.label}
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Activity className="h-3.5 w-3.5" />
                  {overview.system.total_agents} active agents
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Trophy className="h-3.5 w-3.5" />
                  {overview.system.agents_with_history} benchmarked
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  {pressuredAgents} agents under pressure
                </span>
                <span className="inline-flex items-center gap-1.5 rounded-full bg-slate-800/80 px-3 py-1 text-xs font-medium text-slate-200 ring-1 ring-slate-700">
                  <Brain className="h-3.5 w-3.5" />
                  {overview.low_yield_references.length} noisy memories flagged
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
                    {systemStatus?.detail}
                  </p>
                </div>
                <Target className="h-5 w-5 text-amber-500" />
              </div>

              <dl className="grid grid-cols-2 gap-3 text-sm">
                <div className="rounded-xl bg-slate-900 px-3 py-2 ring-1 ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">System score</dt>
                  <dd className="mt-1 font-semibold text-slate-100">
                    {formatScore(overview.system.avg_score)}
                  </dd>
                </div>
                <div className="rounded-xl bg-slate-900 px-3 py-2 ring-1 ring-slate-800">
                  <dt className="text-xs uppercase tracking-wide text-slate-400">Pass rate</dt>
                  <dd className="mt-1 font-semibold text-slate-100">
                    {formatPercent(overview.system.avg_pass_rate)}
                  </dd>
                </div>
              </dl>
            </div>
          </div>
        </section>

        <section className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="group rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-emerald-900/60 animate-fade-up stagger-1">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Coverage</p>
              <div className="h-2 w-2 rounded-full bg-emerald-500/60" />
            </div>
            <p className="mt-3 text-3xl font-semibold text-slate-50">
              {overview.system.agents_with_history}<span className="text-lg text-slate-500">/{overview.system.total_agents}</span>
            </p>
            <p className="mt-2 text-sm text-slate-400">
              {formatPercent(coverageRate)} with Arena evidence
            </p>
          </div>
          <div className="group rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-blue-900/60 animate-fade-up stagger-2">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Runs</p>
              <div className="h-2 w-2 rounded-full bg-blue-500/60" />
            </div>
            <p className="mt-3 text-3xl font-semibold text-slate-50">{overview.system.total_runs}</p>
            <p className="mt-2 text-sm text-slate-400">In current {windowDays}-day window</p>
          </div>
          <div className="group rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-amber-900/60 animate-fade-up stagger-3">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Avg Score</p>
              <div className="h-2 w-2 rounded-full bg-amber-500/60" />
            </div>
            <p className="mt-3 text-3xl font-semibold text-slate-50">{formatScore(overview.system.avg_score)}</p>
            <p className="mt-2 text-sm text-slate-400">Benchmarked agents only</p>
          </div>
          <div className="group rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-rose-900/60 animate-fade-up stagger-4">
            <div className="flex items-center justify-between">
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Regressions</p>
              <div className={cn("h-2 w-2 rounded-full", overview.system.total_regressions > 0 ? "bg-rose-500/80" : "bg-slate-600")} />
            </div>
            <p className="mt-3 text-3xl font-semibold text-slate-50">{overview.system.total_regressions}</p>
            {Object.keys(overview.system.regressions_by_category ?? {}).length > 0 && (
              <p className="mt-1 text-xs text-slate-500">
                {Object.entries(overview.system.regressions_by_category)
                  .map(([cat, count]) => `${cat}: ${count}`)
                  .join(" · ")}
              </p>
            )}
            <p className="mt-2 text-sm text-slate-400">Decision-quality misses</p>
          </div>
        </section>

        <section className="mt-4 rounded-2xl border border-amber-900/30 bg-amber-950/10 px-5 py-4">
          <div className="flex items-center gap-2">
            <div className="h-1 w-1 rounded-full bg-amber-500" />
            <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-400/80">Context</p>
          </div>
          <p className="mt-2 text-sm leading-6 text-slate-300">
            Arena is a triage surface, not a single blended score. The average covers
            {` ${overview.system.agents_with_history} of ${overview.system.total_agents} `}
            agents in this window. The regression count tracks decision-quality misses only —
            JSON/summary-term failures and tool-requirement misses are shown as labeled pulse items below.
          </p>
        </section>

        <section className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-3">
          <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-emerald-900/40">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-100">Daily review</p>
                <p className="mt-1 text-sm text-slate-400">
                  {personaPossessive} evidence review loop for small justified changes.
                </p>
              </div>
              <CalendarClock className="h-5 w-5 text-emerald-500" />
            </div>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Next run</dt>
                <dd className="font-semibold text-slate-100">{formatDateTime(reviewJob?.next_run_at)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Last run</dt>
                <dd className="font-semibold text-slate-100">{formatRelativeTime(reviewJob?.last_run_at)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Run count</dt>
                <dd className="font-semibold text-slate-100">{reviewJob?.run_count ?? 0}</dd>
              </div>
            </dl>
          </article>

          <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-violet-900/40">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-100">Nightly honing</p>
                <p className="mt-1 text-sm text-slate-400">
                  Benchmark-backed self-correction for {personaName} and {personaPossessive} routing choices.
                </p>
              </div>
              <FlaskConical className="h-5 w-5 text-violet-400" />
            </div>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Next run</dt>
                <dd className="font-semibold text-slate-100">{formatDateTime(honingJob?.next_run_at)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Last run</dt>
                <dd className="font-semibold text-slate-100">{formatRelativeTime(honingJob?.last_run_at)}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Run count</dt>
                <dd className="font-semibold text-slate-100">{honingJob?.run_count ?? 0}</dd>
              </div>
            </dl>
          </article>

          <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5 transition-colors hover:border-blue-900/40">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-sm font-semibold text-slate-100">Memory health</p>
                <p className="mt-1 text-sm text-slate-400">
                  Whether injected memory is getting cited, searched, and debugged properly.
                </p>
              </div>
              <Brain className="h-5 w-5 text-blue-400" />
            </div>
            <dl className="mt-4 space-y-3 text-sm">
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Selected ref citation</dt>
                <dd className="font-semibold text-slate-100">
                  {formatPercent(overview.memory_utilization.selected_reference_citation_rate * 100)}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Lookup after injection</dt>
                <dd className="font-semibold text-slate-100">
                  {overview.memory_utilization.lookup_after_injection_sessions}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Debug coverage</dt>
                <dd className="font-semibold text-slate-100">
                  {formatPercent(overview.memory_utilization.memory_debug_coverage_rate * 100)}
                </dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-slate-400">Governance issues</dt>
                <dd className="font-semibold text-slate-100">
                  {memoryGovernance?.issue_count ?? 0}
                </dd>
              </div>
            </dl>
          </article>
        </section>

        <section className="mt-6 grid grid-cols-1 gap-6 xl:grid-cols-[1.05fr_0.95fr]">
          <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <h3 className="text-sm font-semibold text-slate-100">Recent issues</h3>
                <p className="mt-1 text-sm text-slate-400">
                  Latest negative signals that are actually worth {personaPossessive} attention.
                </p>
              </div>
              <AlertTriangle className="h-5 w-5 text-amber-500" />
            </div>
            <div className="mt-4 grid gap-3">
              {overview.repeated_issues.length > 0 ? overview.repeated_issues.slice(0, 4).map((issue) => (
                <article key={`${issue.agent_slug}:${issue.content}`} className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold text-slate-100">{issue.agent_slug}</p>
                      <p className="mt-1 text-xs text-slate-300" title={issue.content}>
                        {summarizeArenaIssue(issue.content, 160)}
                      </p>
                    </div>
                    <div className="flex flex-col items-end gap-1">
                      {issue.feedback_type ? (
                        <span className="rounded-full bg-rose-950/30 px-2 py-1 text-[11px] font-semibold text-rose-200 ring-1 ring-rose-900">
                          {issue.feedback_type}
                        </span>
                      ) : null}
                      <span className="rounded-full bg-amber-950/30 px-2 py-1 text-[11px] font-semibold text-amber-200 ring-1 ring-amber-900">
                        {issue.count}x
                      </span>
                    </div>
                  </div>
                  <p className="mt-2 text-[11px] text-slate-500">Latest {formatDateTime(issue.latest_at)}</p>
                </article>
              )) : (
                <div className="rounded-xl border border-dashed border-emerald-900 bg-emerald-950/20 px-4 py-6 text-center text-sm text-slate-300">
                  No negative issue signals surfaced in the current evidence window.
                </div>
              )}
            </div>
          </article>

          <div className="grid gap-6">
            <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-100">Memory watchlist</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    References that are selected often enough to cost context but rarely cited.
                  </p>
                </div>
                <Search className="h-5 w-5 text-amber-500" />
              </div>
              <div className="mt-4 space-y-3">
                {overview.low_yield_references.length > 0 ? overview.low_yield_references.slice(0, 4).map((item) => (
                  <article key={item.uuid} className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                    <p className="text-sm font-semibold text-slate-100">{item.label}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      selected {item.selected} · cited {item.cited} · rate {formatPercent(item.citation_rate * 100)}
                    </p>
                    {item.tags.length > 0 ? (
                      <p className="mt-2 text-[11px] text-slate-500">{item.tags.join(", ")}</p>
                    ) : null}
                  </article>
                )) : (
                  <div className="rounded-xl border border-dashed border-emerald-900 bg-emerald-950/20 px-4 py-6 text-center text-sm text-slate-300">
                    No obvious noisy references in the current window.
                  </div>
                )}
              </div>
            </article>

            <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-100">Memory governance</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    Structural context-shape issues: broad references, bloated policy, and trigger drift.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <span className={cn(
                    "rounded-full px-2 py-1 text-[11px] font-semibold",
                    deriveMemoryGovernanceTone(memoryGovernance?.health_status ?? "healthy"),
                  )}
                >
                    {memoryGovernance?.health_status ?? "healthy"}
                  </span>
                  <Brain className="h-5 w-5 text-cyan-400" />
                </div>
              </div>
              <div className="mt-4 space-y-3">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Untargeted refs</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-100">
                      {memoryGovernance?.untargeted_reference_count ?? 0}
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Missing summaries</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-100">
                      {memoryGovernance?.missing_reference_summary_count ?? 0}
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Oversized policy</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-100">
                      {memoryGovernance?.oversized_policy_count ?? 0}
                    </p>
                  </div>
                  <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Invalid triggers</p>
                    <p className="mt-2 text-2xl font-semibold text-slate-100">
                      {memoryGovernance?.invalid_trigger_task_type_count ?? 0}
                    </p>
                  </div>
                </div>
                <div className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm text-slate-300">
                  <p className="text-xs uppercase tracking-wide text-slate-500">Agent delivery controls</p>
                  <p className="mt-2 text-slate-400">
                    hard issues {memoryGovernance?.hard_issue_count ?? 0}
                    {" · "}
                    soft issues {memoryGovernance?.soft_issue_count ?? 0}
                    {" · "}
                    threshold breaches {memoryGovernance?.soft_limit_breach_count ?? 0}
                  </p>
                  <p className="mt-2">
                    custom configs {memoryGovernance?.custom_memory_config_agent_count ?? 0} / {memoryGovernance?.active_agent_count ?? 0}
                  </p>
                  <p className="mt-1 text-slate-400">
                    tool ctx off {memoryGovernance?.tool_capabilities_disabled_agent_count ?? 0}
                    {" · "}
                    project index off {memoryGovernance?.project_index_disabled_agent_count ?? 0}
                    {" · "}
                    ref index off {memoryGovernance?.reference_index_disabled_agent_count ?? 0}
                  </p>
                  <p className="mt-1 text-slate-400">
                    agents with UUID exclusions {memoryGovernance?.memory_exclusion_agent_count ?? 0}
                    {" · "}
                    excluded UUIDs {memoryGovernance?.excluded_memory_uuid_count ?? 0}
                  </p>
                </div>
                {memoryGovernance && memoryGovernance.untargeted_reference_samples.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Top untargeted references</p>
                    {memoryGovernance.untargeted_reference_samples.slice(0, 3).map((item) => (
                      <div
                        key={item.uuid}
                        className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm"
                      >
                        <p className="font-semibold text-slate-100">{item.label}</p>
                        {item.details ? (
                          <p className="mt-1 text-xs text-slate-400">{item.details}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {memoryGovernance && memoryGovernance.oversized_policy_samples.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Top oversized policies</p>
                    {memoryGovernance.oversized_policy_samples.slice(0, 3).map((item) => (
                      <div
                        key={item.uuid}
                        className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm"
                      >
                        <p className="font-semibold text-slate-100">{item.label}</p>
                        {item.details ? (
                          <p className="mt-1 text-xs text-slate-400">{item.details}</p>
                        ) : null}
                      </div>
                    ))}
                  </div>
                ) : null}
                {memoryGovernance && memoryGovernance.invalid_trigger_task_type_samples.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Invalid trigger samples</p>
                    {memoryGovernance.invalid_trigger_task_type_samples
                      .slice(0, 3)
                      .map((item) => (
                        <div
                          key={item.uuid}
                          className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm"
                        >
                          <p className="font-semibold text-slate-100">{item.label}</p>
                          <p className="mt-1 text-xs text-slate-400">
                            invalid trigger types: {item.invalid_types.join(", ")}
                          </p>
                        </div>
                      ))}
                  </div>
                ) : null}
                {memoryGovernance && memoryGovernance.startup_profile_agent_target_samples.length > 0 ? (
                  <div className="space-y-2">
                    <p className="text-xs uppercase tracking-wide text-slate-500">Broken startup routes</p>
                    {memoryGovernance.startup_profile_agent_target_samples
                      .slice(0, 3)
                      .map((item) => (
                        <div
                          key={item.uuid}
                          className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm"
                        >
                          <p className="font-semibold text-slate-100">{item.label}</p>
                          {item.details ? (
                            <p className="mt-1 text-xs text-slate-400">{item.details}</p>
                          ) : null}
                        </div>
                      ))}
                  </div>
                ) : null}
                {memoryGovernance
                && memoryGovernance.untargeted_reference_samples.length === 0
                && memoryGovernance.oversized_policy_samples.length === 0
                && memoryGovernance.invalid_trigger_task_type_samples.length === 0
                && memoryGovernance.startup_profile_agent_target_samples.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-emerald-900 bg-emerald-950/20 px-4 py-6 text-center text-sm text-slate-300">
                    No structural memory-governance issues surfaced in the current snapshot.
                  </div>
                ) : null}
              </div>
            </article>

            <article className="rounded-2xl border border-slate-800 bg-slate-900/60 p-5">
              <div className="flex items-start justify-between gap-3">
                <div>
                  <h3 className="text-sm font-semibold text-slate-100">Experiment + regression pulse</h3>
                  <p className="mt-1 text-sm text-slate-400">
                    Recent experiment decisions and open benchmark failures from {personaPossessive} loop.
                  </p>
                </div>
                <Trophy className="h-5 w-5 text-amber-500" />
              </div>
              <div className="mt-4 space-y-3">
                {overview.recent_benchmark_experiments.slice(0, 2).map((experiment) => (
                  <div key={`${experiment.suite_id}:${experiment.decision}`} className="rounded-xl border border-slate-800 bg-slate-950/50 px-4 py-3 text-sm">
                    <p className="font-semibold text-slate-100">{experiment.suite_id}</p>
                    <p className="mt-1 text-xs text-slate-400">
                      decision {experiment.decision} · score {experiment.score_delta.toFixed(1)} · pass {experiment.pass_rate_delta.toFixed(1)}
                    </p>
                    {experiment.decision_reason ? (
                      <p className="mt-1 text-[11px] text-slate-500">{experiment.decision_reason}</p>
                    ) : null}
                  </div>
                ))}
                {overview.open_regression_clusters.slice(0, 2).map((cluster) => (
                  <div key={`${cluster.case_id}:${cluster.failure_detail}`} className="rounded-xl border border-rose-900 bg-rose-950/20 px-4 py-3 text-sm">
                    <div className="flex items-start justify-between gap-3">
                      <p className="font-semibold text-slate-100">{cluster.case_id}</p>
                      {cluster.failure_category ? (
                        <span className="rounded-full bg-slate-900/80 px-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 ring-1 ring-slate-700">
                          {cluster.failure_category}
                        </span>
                      ) : null}
                    </div>
                    <p className="mt-1 text-xs text-slate-300">{cluster.failure_detail}</p>
                  </div>
                ))}
                {overview.recent_benchmark_experiments.length === 0 && overview.open_regression_clusters.length === 0 ? (
                  <div className="rounded-xl border border-dashed border-emerald-900 bg-emerald-950/20 px-4 py-6 text-center text-sm text-slate-300">
                    No active benchmark pressure surfaced in the current window.
                  </div>
                ) : null}
              </div>
            </article>
          </div>
        </section>

        <section className="mt-8">
          <div className="flex items-center justify-between gap-3">
            <div>
              <h3 className="text-sm font-semibold uppercase tracking-[0.18em] text-slate-400">Agent Breakdown</h3>
              <p className="mt-2 text-sm text-slate-400">
                Sorted by pressure — regressions, score, and signal volume.
              </p>
            </div>
          </div>

          {overview.agents.length > 0 ? (
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
              {overview.agents.map((agent) => (
                <ArenaAgentCard
                  key={agent.slug}
                  agent={agent}
                />
              ))}
            </div>
          ) : (
            <div className="mt-4 empty-surface animate-fade-up">
              <p className="text-sm font-medium text-slate-300">No agents found.</p>
              <p className="mt-2 text-xs text-slate-500">
                Create an agent to start building Arena evidence.
              </p>
            </div>
          )}
        </section>
      </main>
    </div>
  );
}
