'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  AlertCircle,
  AlertTriangle,
  Calendar,
  Check,
  Clock,
  DollarSign,
  TrendingUp,
} from 'lucide-react'
import { useCallback, useState } from 'react'
import {
  type BudgetSettingsUpdate,
  fetchAllProjectBudgets,
  type ProjectBudget,
  updateBudgetSettings,
} from '@/lib/api'
import { formatCurrency } from '@/lib/formatters'
import { BudgetRow } from './_budget-row'
import { OverviewCard } from './_components'

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BudgetManagementPage() {
  const queryClient = useQueryClient()
  const [editingProject, setEditingProject] = useState<string | null>(null)

  const {
    data: budgets,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['project-budgets'],
    queryFn: fetchAllProjectBudgets,
    refetchInterval: 30000,
  })

  const mutation = useMutation({
    mutationFn: ({
      projectId,
      update,
    }: {
      projectId: string
      update: BudgetSettingsUpdate
    }) => updateBudgetSettings(projectId, update),
    onMutate: async ({ projectId, update }) => {
      await queryClient.cancelQueries({ queryKey: ['project-budgets'] })
      const previous = queryClient.getQueryData<ProjectBudget[]>([
        'project-budgets',
      ])
      queryClient.setQueryData<ProjectBudget[]>(['project-budgets'], (old) =>
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
      )
      return { previous }
    },
    onError: (_err, _vars, context) => {
      if (context?.previous) {
        queryClient.setQueryData(['project-budgets'], context.previous)
      }
    },
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: ['project-budgets'] })
    },
  })

  const handleSave = useCallback(
    (projectId: string, update: BudgetSettingsUpdate) => {
      mutation.mutate({ projectId, update })
    },
    [mutation],
  )

  // ─── Compute overview stats ───────────────────────────────────────────────

  const totalDailySpend =
    budgets?.reduce((sum, b) => sum + b.daily.used, 0) ?? 0
  const totalMonthlySpend =
    budgets?.reduce((sum, b) => sum + b.monthly.used, 0) ?? 0
  const warningCount =
    budgets?.filter((b) => b.alert_level === 'warning').length ?? 0
  const criticalCount =
    budgets?.filter((b) => b.alert_level === 'critical').length ?? 0
  const alertCount = warningCount + criticalCount
  const overviewStatus =
    criticalCount > 0 ? 'error' : warningCount > 0 ? 'warning' : 'success'

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

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
          <LoadingSkeletons />
        ) : budgets?.length === 0 ? (
          <EmptyState />
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
                    ? 'All projects within limits'
                    : `${criticalCount} critical, ${warningCount} warning`
                }
                icon={AlertTriangle}
                status={
                  criticalCount > 0
                    ? 'error'
                    : warningCount > 0
                      ? 'warning'
                      : 'success'
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
                    {[
                      'Project',
                      'Daily Spend',
                      'Monthly Spend',
                      'Alert Level',
                    ].map((h) => (
                      <th
                        key={h}
                        className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400"
                      >
                        {h}
                      </th>
                    ))}
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
  )
}

// ─── Loading skeletons ────────────────────────────────────────────────────────

function LoadingSkeletons() {
  return (
    <>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="h-32 rounded-2xl animate-shimmer" />
        ))}
      </div>
      <div className="space-y-2">
        {[1, 2, 3, 4, 5].map((i) => (
          <div key={i} className="h-14 rounded-xl animate-shimmer" />
        ))}
      </div>
    </>
  )
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400">
      <DollarSign className="h-12 w-12 mb-4 opacity-40" />
      <p className="text-lg mb-1">No cost budgets configured</p>
      <p className="text-xs text-slate-500">
        Set daily and monthly cost limits on the{' '}
        <a
          href="/access-control/permissions"
          className="text-amber-400 hover:text-amber-300 underline underline-offset-2"
        >
          permissions page
        </a>{' '}
        to start tracking spend
      </p>
    </div>
  )
}
