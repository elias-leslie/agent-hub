"use client";

import { Database, Clock, Layers, Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import type { MemoryStats } from "@/lib/memory-api";

interface MemoryStatsProps {
  stats: MemoryStats | undefined;
  isLoading: boolean;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const date = new Date(dateStr);
  return date.toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function getCategoryIcon(category: string): string {
  const icons: Record<string, string> = {
    coding_standard: "📏",
    troubleshooting_guide: "⚠️",
    system_design: "🏗️",
    operational_context: "⚙️",
    domain_knowledge: "📚",
    active_state: "▶️",
  };
  return icons[category] || "📝";
}

function getScopeLabel(scope: string): string {
  const labels: Record<string, string> = {
    global: "Global",
    project: "Project",
    task: "Task",
  };
  return labels[scope] || scope;
}

function StatCard({
  icon: Icon,
  label,
  value,
  subtext,
  accentColor = "emerald",
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: string | number;
  subtext?: string;
  accentColor?: "emerald" | "amber" | "blue" | "purple";
}) {
  const colors = {
    emerald: "border-l-emerald-500 dark:border-l-emerald-400",
    amber: "border-l-amber-500 dark:border-l-amber-400",
    blue: "border-l-blue-500 dark:border-l-blue-400",
    purple: "border-l-purple-500 dark:border-l-purple-400",
  };

  return (
    <div
      className={cn(
        "border-l-4 rounded-lg p-4",
        "bg-white dark:bg-slate-900/50",
        "border border-slate-200 dark:border-slate-800",
        colors[accentColor],
      )}
      data-testid="stat-card"
    >
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm text-slate-500 dark:text-slate-400">{label}</p>
          <p className="text-2xl font-semibold text-slate-900 dark:text-slate-100 mt-1">
            {value}
          </p>
          {subtext && (
            <p className="text-xs text-slate-400 dark:text-slate-500 mt-1">
              {subtext}
            </p>
          )}
        </div>
        <Icon className="w-5 h-5 text-slate-400 dark:text-slate-500" />
      </div>
    </div>
  );
}

function SkeletonCard() {
  return (
    <div className="border-l-4 border-l-slate-300 dark:border-l-slate-700 rounded-lg p-4 bg-white dark:bg-slate-900/50 border border-slate-200 dark:border-slate-800">
      <div className="animate-pulse">
        <div className="h-4 w-20 bg-slate-200 dark:bg-slate-700 rounded" />
        <div className="h-8 w-16 bg-slate-200 dark:bg-slate-700 rounded mt-2" />
      </div>
    </div>
  );
}

export function MemoryStats({ stats, isLoading }: MemoryStatsProps) {
  if (isLoading) {
    return (
      <div
        className="grid grid-cols-2 lg:grid-cols-4 gap-4"
        data-testid="memory-stats"
      >
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
        <SkeletonCard />
      </div>
    );
  }

  if (!stats) {
    return null;
  }

  // Get top 2 categories and scopes for display
  const topCategories = stats.by_category.slice(0, 2);
  const topScopes = stats.by_scope.slice(0, 3);

  return (
    <div
      className="grid grid-cols-2 lg:grid-cols-4 gap-4"
      data-testid="memory-stats"
    >
      <StatCard
        icon={Database}
        label="Total Memories"
        value={stats.total}
        accentColor="emerald"
      />
      <StatCard
        icon={Clock}
        label="Last Updated"
        value={formatDate(stats.last_updated)}
        accentColor="blue"
      />
      <StatCard
        icon={Brain}
        label="By Scope"
        value={topScopes.length > 0 ? topScopes[0].count : 0}
        subtext={
          topScopes.length > 0
            ? topScopes.map((s) => `${getScopeLabel(s.scope)}: ${s.count}`).join(", ")
            : undefined
        }
        accentColor="amber"
      />
      <StatCard
        icon={Layers}
        label="Categories"
        value={stats.by_category.length}
        subtext={
          topCategories.length > 0
            ? topCategories.map((c) => `${getCategoryIcon(c.category)} ${c.count}`).join(" ")
            : undefined
        }
        accentColor="purple"
      />
    </div>
  );
}
