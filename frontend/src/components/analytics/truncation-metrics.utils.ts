import type { SeverityLevel, SeverityStyles } from "./truncation-metrics.types";

export const formatNumber = (n: number) => n.toLocaleString();

export const formatPercent = (n: number) => `${n.toFixed(1)}%`;

export const formatTime = (dateStr: string) => {
  const date = new Date(dateStr);
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
};

export const getSeverityLevel = (truncationRate: number): SeverityLevel => {
  if (truncationRate > 10) return "high";
  if (truncationRate > 5) return "medium";
  return "low";
};

export const severityStyles: Record<SeverityLevel, SeverityStyles> = {
  low: {
    bg: "from-emerald-50 to-teal-50/50 dark:from-emerald-950/30 dark:to-teal-950/20",
    border: "border-emerald-200/60 dark:border-emerald-800/40",
    accent: "text-emerald-600 dark:text-emerald-400",
    glow: "shadow-emerald-100 dark:shadow-emerald-900/20",
  },
  medium: {
    bg: "from-amber-50 to-orange-50/50 dark:from-amber-950/30 dark:to-orange-950/20",
    border: "border-amber-200/60 dark:border-amber-800/40",
    accent: "text-amber-600 dark:text-amber-400",
    glow: "shadow-amber-100 dark:shadow-amber-900/20",
  },
  high: {
    bg: "from-rose-50 to-red-50/50 dark:from-rose-950/30 dark:to-red-950/20",
    border: "border-rose-200/60 dark:border-rose-800/40",
    accent: "text-rose-600 dark:text-rose-400",
    glow: "shadow-rose-100 dark:shadow-rose-900/20",
  },
};
