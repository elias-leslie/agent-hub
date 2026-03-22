import type { AgentBenchmarkDashboard } from "@/app/agents/[slug]/analytics/types";

export function formatRelativeTime(iso: string | null | undefined) {
  if (!iso) {
    return "No completed runs yet";
  }
  const value = new Date(iso).getTime();
  if (Number.isNaN(value)) {
    return "Unknown";
  }
  const diffMs = Date.now() - value;
  const diffHours = Math.max(Math.round(diffMs / (1000 * 60 * 60)), 0);
  if (diffHours < 1) {
    return "Less than an hour ago";
  }
  if (diffHours < 24) {
    return `${diffHours}h ago`;
  }
  const diffDays = Math.round(diffHours / 24);
  if (diffDays < 30) {
    return `${diffDays}d ago`;
  }
  return new Date(iso).toLocaleDateString();
}

export function formatArenaLabel(value: string | null | undefined) {
  if (!value) {
    return "Unknown";
  }
  return value.replace(/\bjenny\b/gi, "persona");
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Pending";
  }
  return `${value.toFixed(1)}%`;
}

export function formatScore(value: number | null | undefined) {
  if (value === null || value === undefined) {
    return "Pending";
  }
  return value.toFixed(1);
}

export interface ArenaStatus {
  label: string;
  tone: string;
  detail: string;
}

const STATUS_TONES = {
  regression: "bg-rose-950/30 text-rose-300 ring-1 ring-rose-800",
  watch: "bg-amber-950/30 text-amber-300 ring-1 ring-amber-800",
  stable: "bg-emerald-950/30 text-emerald-300 ring-1 ring-emerald-800",
} as const;

export function deriveArenaStatus(benchmarkDashboard: AgentBenchmarkDashboard): ArenaStatus {
  const { avg_score: avgScore, pass_rate: passRate, open_regressions: regressions } =
    benchmarkDashboard.overview;
  if (regressions >= 3 || passRate < 60) {
    return {
      label: "Regression pressure",
      tone: STATUS_TONES.regression,
      detail: "Arena is catching active failures that still need reduction before trust increases.",
    };
  }
  if (regressions > 0 || avgScore < 90) {
    return {
      label: "Under watch",
      tone: STATUS_TONES.watch,
      detail: "Core behavior is mostly intact, but there are still open weaknesses in the benchmark battery.",
    };
  }
  return {
    label: "Stable",
    tone: STATUS_TONES.stable,
    detail: "Recent runs are holding their ground with low regression pressure and solid benchmark scores.",
  };
}
