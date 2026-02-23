"use client";

import { useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  DollarSign,
  AlertTriangle,
  AlertCircle,
  Check,
  Pencil,
  X,
  TrendingUp,
  Calendar,
  Clock,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { formatCurrency } from "@/lib/formatters";
import {
  fetchAllProjectBudgets,
  updateBudgetSettings,
  type ProjectBudget,
  type BudgetSettingsUpdate,
} from "@/lib/api";

// ─── Alert level config ──────────────────────────────────────────────────────

const ALERT_CONFIG = {
  warning: {
    label: "Warning",
    icon: AlertTriangle,
    textColor: "text-amber-400",
    bgColor: "bg-amber-500/10",
    borderColor: "border-amber-500/30",
  },
  critical: {
    label: "Critical",
    icon: AlertCircle,
    textColor: "text-red-400",
    bgColor: "bg-red-500/10",
    borderColor: "border-red-500/30",
  },
} as const;

// ─── Progress bar color helpers ──────────────────────────────────────────────

function getProgressColor(used: number, limit: number | null): string {
  if (limit === null || limit === 0) return "bg-slate-600";
  const pct = used / limit;
  if (pct >= 0.9) return "bg-red-500";
  if (pct >= 0.7) return "bg-amber-500";
  return "bg-emerald-500";
}

function getProgressBgColor(used: number, limit: number | null): string {
  if (limit === null || limit === 0) return "bg-slate-800";
  const pct = used / limit;
  if (pct >= 0.9) return "bg-red-500/10";
  if (pct >= 0.7) return "bg-amber-500/10";
  return "bg-emerald-500/10";
}

function getProgressPercent(used: number, limit: number | null): number {
  if (limit === null || limit === 0) return 0;
  return Math.min((used / limit) * 100, 100);
}

// ─── Alert level badge ───────────────────────────────────────────────────────

function AlertBadge({ level }: { level: "warning" | "critical" | null }) {
  if (!level) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-slate-500/10 text-slate-500">
        None
      </span>
    );
  }

  const config = ALERT_CONFIG[level];
  const Icon = config.icon;

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium border",
        config.bgColor,
        config.textColor,
        config.borderColor,
      )}
    >
      <Icon className="h-3 w-3" />
      {config.label}
    </span>
  );
}

// ─── Budget progress bar ─────────────────────────────────────────────────────

function BudgetBar({
  used,
  limit,
}: {
  used: number;
  limit: number | null;
}) {
  const percent = getProgressPercent(used, limit);
  const barColor = getProgressColor(used, limit);
  const bgColor = getProgressBgColor(used, limit);

  if (limit === null) {
    return (
      <div className="flex items-center gap-2">
        <span className="text-sm font-mono text-slate-300">
          {formatCurrency(used)}
        </span>
        <span className="text-[11px] text-slate-600">/ no limit</span>
      </div>
    );
  }

  return (
    <div className="min-w-[160px]">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-sm font-mono text-slate-300">
          {formatCurrency(used)}
        </span>
        <span className="text-[11px] text-slate-500">
          / {formatCurrency(limit)}
        </span>
      </div>
      <div className={cn("h-1.5 rounded-full overflow-hidden", bgColor)}>
        <div
          className={cn("h-full rounded-full transition-all duration-500", barColor)}
          style={{ width: `${percent}%` }}
        />
      </div>
      <div className="mt-0.5 text-right">
        <span className="text-[10px] text-slate-600">
          {percent.toFixed(0)}%
        </span>
      </div>
    </div>
  );
}

// ─── Save flash indicator ────────────────────────────────────────────────────

function SaveFlash({ saving, error }: { saving: boolean; error: boolean }) {
  if (!saving && !error) return null;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium",
        "animate-pulse",
        error
          ? "bg-red-900/30 text-red-400"
          : "bg-emerald-900/30 text-emerald-400",
      )}
    >
      {error ? (
        <>
          <AlertCircle className="h-3 w-3" /> Error
        </>
      ) : (
        <>
          <Check className="h-3 w-3" /> Saved
        </>
      )}
    </span>
  );
}

// ─── Inline budget editor ────────────────────────────────────────────────────

function BudgetEditor({
  budget,
  onSave,
  onCancel,
}: {
  budget: ProjectBudget;
  onSave: (projectId: string, update: BudgetSettingsUpdate) => void;
  onCancel: () => void;
}) {
  const [dailyLimit, setDailyLimit] = useState<string>(
    budget.daily.limit !== null ? String(budget.daily.limit) : "",
  );
  const [monthlyLimit, setMonthlyLimit] = useState<string>(
    budget.monthly.limit !== null ? String(budget.monthly.limit) : "",
  );
  const [alertThreshold, setAlertThreshold] = useState<string>("0.8");

  const handleSave = () => {
    const update: BudgetSettingsUpdate = {
      daily_cost_budget_usd: dailyLimit ? parseFloat(dailyLimit) : null,
      monthly_cost_budget_usd: monthlyLimit ? parseFloat(monthlyLimit) : null,
      budget_alert_threshold: alertThreshold
        ? parseFloat(alertThreshold)
        : null,
    };
    onSave(budget.project_id, update);
  };

  const inputClassName = cn(
    "w-24 bg-slate-800/60 border border-slate-700/80 rounded-md",
    "px-2 py-1 text-sm text-slate-300 font-mono",
    "focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500/50",
    "hover:border-slate-600 transition-colors",
    "placeholder:text-slate-600",
  );

  return (
    <td colSpan={5} className="px-4 py-3">
      <div className="flex items-center gap-6 bg-slate-800/30 rounded-lg p-3 border border-slate-700/50">
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 whitespace-nowrap">
            Daily limit ($)
          </label>
          <input
            type="number"
            step="0.01"
            min="0"
            placeholder="None"
            value={dailyLimit}
            onChange={(e) => setDailyLimit(e.target.value)}
            className={inputClassName}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 whitespace-nowrap">
            Monthly limit ($)
          </label>
          <input
            type="number"
            step="0.01"
            min="0"
            placeholder="None"
            value={monthlyLimit}
            onChange={(e) => setMonthlyLimit(e.target.value)}
            className={inputClassName}
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-xs text-slate-400 whitespace-nowrap">
            Alert at (%)
          </label>
          <input
            type="number"
            step="0.05"
            min="0"
            max="1"
            placeholder="0.8"
            value={alertThreshold}
            onChange={(e) => setAlertThreshold(e.target.value)}
            className={cn(inputClassName, "w-16")}
          />
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={handleSave}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              "bg-emerald-600/20 text-emerald-400 border border-emerald-600/30",
              "hover:bg-emerald-600/30 transition-colors",
            )}
          >
            <Check className="h-3.5 w-3.5" />
            Save
          </button>
          <button
            type="button"
            onClick={onCancel}
            className={cn(
              "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium",
              "bg-slate-700/30 text-slate-400 border border-slate-700/50",
              "hover:bg-slate-700/50 transition-colors",
            )}
          >
            <X className="h-3.5 w-3.5" />
            Cancel
          </button>
        </div>
      </div>
    </td>
  );
}

// ─── Budget row ──────────────────────────────────────────────────────────────

function BudgetRow({
  budget,
  isEditing,
  onEdit,
  onCancelEdit,
  onSave,
}: {
  budget: ProjectBudget;
  isEditing: boolean;
  onEdit: () => void;
  onCancelEdit: () => void;
  onSave: (projectId: string, update: BudgetSettingsUpdate) => void;
}) {
  const [savingField, setSavingField] = useState<string | null>(null);
  const [errorField, setErrorField] = useState<string | null>(null);

  const handleSave = useCallback(
    (projectId: string, update: BudgetSettingsUpdate) => {
      setSavingField("budget");
      setErrorField(null);
      onSave(projectId, update);
      setTimeout(() => setSavingField(null), 1200);
    },
    [onSave],
  );

  // Determine a dot color based on alert level (fallback to slate)
  const dotColor =
    budget.alert_level === "critical"
      ? "bg-red-500"
      : budget.alert_level === "warning"
        ? "bg-amber-500"
        : "bg-emerald-500";

  if (isEditing) {
    return (
      <tr className="bg-slate-800/10">
        <BudgetEditor
          budget={budget}
          onSave={(pid, update) => {
            handleSave(pid, update);
            onCancelEdit();
          }}
          onCancel={onCancelEdit}
        />
      </tr>
    );
  }

  return (
    <tr className="group hover:bg-slate-800/20 transition-colors">
      {/* Project */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div
            className={cn("w-1 h-8 rounded-full flex-shrink-0", dotColor)}
          />
          <div>
            <p className="text-sm font-semibold text-slate-100">
              {budget.project_id}
            </p>
          </div>
        </div>
      </td>

      {/* Daily spend */}
      <td className="px-4 py-3.5">
        <BudgetBar used={budget.daily.used} limit={budget.daily.limit} />
      </td>

      {/* Monthly spend */}
      <td className="px-4 py-3.5">
        <BudgetBar used={budget.monthly.used} limit={budget.monthly.limit} />
      </td>

      {/* Alert level */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <AlertBadge level={budget.alert_level} />
          <SaveFlash
            saving={savingField === "budget"}
            error={errorField === "budget"}
          />
        </div>
      </td>

      {/* Actions */}
      <td className="px-4 py-3.5">
        <button
          type="button"
          onClick={onEdit}
          className={cn(
            "flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium",
            "text-slate-400 border border-slate-700/60 bg-slate-800/40",
            "hover:text-slate-200 hover:bg-slate-800 hover:border-slate-600",
            "opacity-0 group-hover:opacity-100 transition-all",
          )}
        >
          <Pencil className="h-3 w-3" />
          Edit
        </button>
      </td>
    </tr>
  );
}

// ─── Overview stat card ──────────────────────────────────────────────────────

function OverviewCard({
  label,
  value,
  subtext,
  icon: Icon,
  status = "neutral",
}: {
  label: string;
  value: string;
  subtext?: string;
  icon: React.ComponentType<{ className?: string }>;
  status?: "success" | "warning" | "error" | "neutral";
}) {
  const statusConfig = {
    success: { border: "border-l-emerald-500" },
    warning: { border: "border-l-amber-500" },
    error: { border: "border-l-red-500" },
    neutral: { border: "border-l-slate-600" },
  };

  const config = statusConfig[status];

  return (
    <div
      className={cn(
        "relative overflow-hidden",
        "bg-slate-900/60 backdrop-blur-sm",
        "border border-slate-800/80",
        "border-l-[3px]",
        config.border,
        "rounded-lg",
        "p-5",
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-semibold uppercase tracking-widest text-slate-400">
              {label}
            </span>
          </div>
          <p className="mt-2 text-3xl font-semibold tracking-tight text-slate-50 font-mono tabular-nums">
            {value}
          </p>
          {subtext && (
            <p className="mt-1 text-xs text-slate-400">{subtext}</p>
          )}
        </div>
        <div className="p-2 rounded-md bg-slate-800/80">
          <Icon className="h-5 w-5 text-slate-400" />
        </div>
      </div>
    </div>
  );
}

// ─── Main page ───────────────────────────────────────────────────────────────

export default function BudgetManagementPage() {
  const queryClient = useQueryClient();
  const [editingProject, setEditingProject] = useState<string | null>(null);

  const {
    data: budgets,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["project-budgets"],
    queryFn: fetchAllProjectBudgets,
    refetchInterval: 30000,
  });

  const mutation = useMutation({
    mutationFn: ({
      projectId,
      update,
    }: {
      projectId: string;
      update: BudgetSettingsUpdate;
    }) => updateBudgetSettings(projectId, update),
    onMutate: async ({ projectId, update }) => {
      await queryClient.cancelQueries({ queryKey: ["project-budgets"] });
      const previous = queryClient.getQueryData<ProjectBudget[]>([
        "project-budgets",
      ]);

      queryClient.setQueryData<ProjectBudget[]>(
        ["project-budgets"],
        (old) =>
          old?.map((b) =>
            b.project_id === projectId
              ? {
                  ...b,
                  daily: {
                    ...b.daily,
                    limit:
                      update.daily_cost_budget_usd !== undefined
                        ? update.daily_cost_budget_usd
                        : b.daily.limit,
                    remaining:
                      update.daily_cost_budget_usd !== undefined &&
                      update.daily_cost_budget_usd !== null
                        ? update.daily_cost_budget_usd - b.daily.used
                        : b.daily.remaining,
                  },
                  monthly: {
                    ...b.monthly,
                    limit:
                      update.monthly_cost_budget_usd !== undefined
                        ? update.monthly_cost_budget_usd
                        : b.monthly.limit,
                    remaining:
                      update.monthly_cost_budget_usd !== undefined &&
                      update.monthly_cost_budget_usd !== null
                        ? update.monthly_cost_budget_usd - b.monthly.used
                        : b.monthly.remaining,
                  },
                }
              : b,
          ),
      );
      return { previous };
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(["project-budgets"], context.previous);
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ["project-budgets"] });
    },
  });

  const handleSave = useCallback(
    (projectId: string, update: BudgetSettingsUpdate) => {
      mutation.mutate({ projectId, update });
    },
    [mutation],
  );

  // ─── Compute overview stats ──────────────────────────────────────────────

  const totalDailySpend =
    budgets?.reduce((sum, b) => sum + b.daily.used, 0) ?? 0;
  const totalMonthlySpend =
    budgets?.reduce((sum, b) => sum + b.monthly.used, 0) ?? 0;
  const warningCount =
    budgets?.filter((b) => b.alert_level === "warning").length ?? 0;
  const criticalCount =
    budgets?.filter((b) => b.alert_level === "critical").length ?? 0;
  const alertCount = warningCount + criticalCount;

  const overviewStatus = criticalCount > 0 ? "error" : warningCount > 0 ? "warning" : "success";

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      {/* Header */}
      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <DollarSign className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">
              Cost Budgets
            </h1>
            {budgets && (
              <span className="text-xs text-slate-500">
                ({budgets.length} projects)
              </span>
            )}
          </div>

          {/* Summary pills */}
          {budgets && budgets.length > 0 && (
            <div className="flex items-center gap-2">
              {criticalCount > 0 && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-red-500/10 text-red-400">
                  <AlertCircle className="h-3 w-3" />
                  {criticalCount} critical
                </span>
              )}
              {warningCount > 0 && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-500/10 text-amber-400">
                  <AlertTriangle className="h-3 w-3" />
                  {warningCount} warning
                </span>
              )}
              {alertCount === 0 && (
                <span className="flex items-center gap-1.5 px-2 py-0.5 rounded text-[11px] font-medium bg-emerald-500/10 text-emerald-400">
                  <Check className="h-3 w-3" />
                  All within budget
                </span>
              )}
            </div>
          )}
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {/* Error banner */}
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">
              Failed to load project budgets
            </p>
          </div>
        )}

        {isLoading ? (
          /* Loading skeletons */
          <>
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              {[1, 2, 3, 4].map((i) => (
                <div
                  key={i}
                  className="h-32 bg-slate-800/40 rounded-lg animate-pulse"
                />
              ))}
            </div>
            <div className="space-y-2">
              {[1, 2, 3, 4, 5].map((i) => (
                <div
                  key={i}
                  className="h-14 bg-slate-800/40 rounded animate-pulse"
                />
              ))}
            </div>
          </>
        ) : budgets?.length === 0 ? (
          /* Empty state */
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <DollarSign className="h-12 w-12 mb-4 opacity-40" />
            <p className="text-lg mb-1">No cost budgets configured</p>
            <p className="text-xs text-slate-500">
              Set daily and monthly cost limits on the{" "}
              <a
                href="/access-control/permissions"
                className="text-amber-400 hover:text-amber-300 underline underline-offset-2"
              >
                permissions page
              </a>{" "}
              to start tracking spend
            </p>
          </div>
        ) : (
          <>
            {/* Overview cards */}
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
              <OverviewCard
                label="Daily Spend"
                value={formatCurrency(totalDailySpend)}
                subtext="Across all projects today"
                icon={Clock}
                status={overviewStatus}
              />
              <OverviewCard
                label="Monthly Spend"
                value={formatCurrency(totalMonthlySpend)}
                subtext="Across all projects this month"
                icon={Calendar}
                status={overviewStatus}
              />
              <OverviewCard
                label="Active Alerts"
                value={String(alertCount)}
                subtext={
                  alertCount === 0
                    ? "All projects within limits"
                    : `${criticalCount} critical, ${warningCount} warning`
                }
                icon={AlertTriangle}
                status={
                  criticalCount > 0
                    ? "error"
                    : warningCount > 0
                      ? "warning"
                      : "success"
                }
              />
              <OverviewCard
                label="Projects Tracked"
                value={String(budgets?.length ?? 0)}
                subtext="With budget data"
                icon={TrendingUp}
                status="neutral"
              />
            </div>

            {/* Budget table */}
            <div className="overflow-hidden rounded-lg border border-slate-800/80">
              <table className="w-full">
                <thead className="bg-slate-800/50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Project
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Daily Spend
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Monthly Spend
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      Alert Level
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400">
                      <span className="sr-only">Actions</span>
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800/50">
                  {budgets?.map((b) => (
                    <BudgetRow
                      key={b.project_id}
                      budget={b}
                      isEditing={editingProject === b.project_id}
                      onEdit={() => setEditingProject(b.project_id)}
                      onCancelEdit={() => setEditingProject(null)}
                      onSave={handleSave}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
