"use client";

import Link from "next/link";
import { AlertTriangle, FlaskConical, Trophy } from "lucide-react";

import type { ArenaAgentSummary } from "@/app/arena/types";
import {
  deriveArenaStatusFromBenchmark,
  formatPercent,
  formatRelativeTime,
  formatScore,
  summarizeArenaIssue,
} from "../utils";

interface ArenaAgentCardProps {
  agent: ArenaAgentSummary;
}

export function ArenaAgentCard({ agent }: ArenaAgentCardProps) {
  const status = deriveArenaStatusFromBenchmark(agent.benchmark);
  const hasHistory = agent.benchmark.total_runs > 0;
  const signalCount = agent.signal_volume
    ? agent.signal_volume.friction + agent.signal_volume.improvement + agent.signal_volume.idea + agent.signal_volume.praise
    : 0;

  return (
    <Link
      href={`/arena/${agent.slug}`}
      prefetch={false}
      className="group relative flex flex-col rounded-2xl border border-slate-800 bg-slate-900/90 p-5 transition-all hover:border-amber-800 hover:shadow-md hover:shadow-amber-950/20"
    >
      <div className="pointer-events-none absolute inset-0 rounded-2xl opacity-0 transition-opacity group-hover:opacity-100 bg-[radial-gradient(circle_at_top_left,oklch(0.75_0.18_55_/_0.04),transparent_50%)]" />

      <div className="relative flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <FlaskConical className="h-4 w-4 text-amber-500" />
            <h3 className="truncate text-sm font-semibold text-slate-100">
              {agent.name}
            </h3>
          </div>
          <p className="mt-1 text-xs text-slate-400">{agent.slug}</p>
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
              <dt className="text-xs uppercase tracking-wide text-slate-400">
                Score
              </dt>
              <dd className="mt-1 inline-flex items-center gap-1.5 font-semibold text-slate-100">
                <Trophy className="h-3.5 w-3.5 text-amber-500" />
                {formatScore(agent.benchmark.avg_score)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-400">
                Pass rate
              </dt>
              <dd className="mt-1 font-semibold text-slate-100">
                {formatPercent(agent.benchmark.pass_rate)}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-400">
                Runs
              </dt>
              <dd className="mt-1 font-semibold text-slate-100">
                {agent.benchmark.total_runs}
              </dd>
            </div>
            <div>
              <dt className="text-xs uppercase tracking-wide text-slate-400">
                Regressions
              </dt>
              <dd className="mt-1 inline-flex items-center gap-1.5 font-semibold text-slate-100">
                {agent.benchmark.open_regressions > 0 && (
                  <AlertTriangle className="h-3.5 w-3.5 text-rose-500" />
                )}
                {agent.benchmark.open_regressions}
              </dd>
            </div>
          </dl>

          <div className="relative mt-4 flex flex-wrap gap-2 text-[11px]">
            <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200 ring-1 ring-slate-700">
              Last run: {formatRelativeTime(agent.benchmark.latest_completed_at)}
            </span>
            {signalCount > 0 ? (
              <span className="rounded-full bg-amber-950/30 px-2 py-1 text-amber-200 ring-1 ring-amber-900">
                {signalCount} recent signals
              </span>
            ) : null}
          </div>
          {agent.top_issue ? (
            <p className="relative mt-3 line-clamp-2 text-xs text-slate-400" title={agent.top_issue.content}>
              {summarizeArenaIssue(agent.top_issue.content, 120)}
            </p>
          ) : null}
        </>
      ) : (
        <>
          <p className="relative mt-4 text-sm text-slate-400">
            No benchmark history yet
          </p>
          {agent.top_issue ? (
            <p className="relative mt-3 line-clamp-2 text-xs text-slate-400" title={agent.top_issue.content}>
              {summarizeArenaIssue(agent.top_issue.content, 120)}
            </p>
          ) : null}
        </>
      )}
    </Link>
  );
}
