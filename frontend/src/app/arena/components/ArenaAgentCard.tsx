"use client";

import Link from "next/link";
import { AlertTriangle, FlaskConical, Trophy } from "lucide-react";

import type { AgentBenchmarkDashboard } from "@/app/agents/[slug]/analytics/types";
import { deriveArenaStatus, formatPercent, formatRelativeTime, formatScore } from "../utils";

interface ArenaAgentCardProps {
  agentName: string;
  slug: string;
  dashboard: AgentBenchmarkDashboard;
}

export function ArenaAgentCard({ agentName, slug, dashboard }: ArenaAgentCardProps) {
  const status = deriveArenaStatus(dashboard);
  const { overview } = dashboard;
  const hasHistory = overview.total_runs > 0;

  return (
    <Link
      href={`/arena/${slug}`}
      className="group relative flex flex-col rounded-2xl border border-slate-200 bg-white/90 p-5 transition-all hover:border-cyan-300 hover:shadow-md dark:border-slate-800 dark:bg-slate-900/90 dark:hover:border-cyan-800"
    >
      <div className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity group-hover:opacity-100 bg-[radial-gradient(circle_at_top_left,rgba(34,211,238,0.06),transparent_50%)]" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-cyan-600 dark:text-cyan-400" />
            <h3 className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">
              {agentName}
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-500 dark:text-slate-400">{slug}</p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-1 text-[11px] font-semibold ${status.tone}`}
        >
          {status.label}
        </span>
      </div>

      {hasHistory ? (
        <>
          <dl className="relative mt-4 grid grid-cols-2 gap-3 text-sm">
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Score
              </dt>
              <dd className="mt-1 inline-flex items-center gap-1.5 font-semibold text-slate-900 dark:text-slate-100">
                <Trophy className="h-3.5 w-3.5 text-amber-500" />
                {formatScore(overview.avg_score)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Pass rate
              </dt>
              <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                {formatPercent(overview.pass_rate)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Runs
              </dt>
              <dd className="mt-1 font-semibold text-slate-900 dark:text-slate-100">
                {overview.total_runs}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
                Regressions
              </dt>
              <dd className="mt-1 inline-flex items-center gap-1.5 font-semibold text-slate-900 dark:text-slate-100">
                {overview.open_regressions > 0 && (
                  <AlertTriangle className="h-3.5 w-3.5 text-rose-500" />
                )}
                {overview.open_regressions}
              </dd>
            </div>
          </dl>

          <p className="relative mt-4 text-xs text-slate-500 dark:text-slate-400">
            Last run: {formatRelativeTime(overview.latest_completed_at)}
          </p>
        </>
      ) : (
        <p className="relative mt-4 text-sm text-slate-500 dark:text-slate-400">
          No benchmark history yet
        </p>
      )}
    </Link>
  );
}
