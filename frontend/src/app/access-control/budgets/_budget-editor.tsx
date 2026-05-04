'use client'

import { Check, X } from 'lucide-react'
import { useState } from 'react'
import type { BudgetSettingsUpdate, ProjectBudget } from '@/lib/api'
import { cn } from '@/lib/utils'

const INPUT_BASE = cn(
  'w-24 bg-slate-800/60 border border-slate-700/80 rounded-md',
  'px-2 py-1 text-sm text-slate-300 font-mono',
  'focus:outline-none focus:ring-1 focus:ring-amber-500/50 focus:border-amber-500/50',
  'hover:border-slate-600 transition-colors',
  'placeholder:text-slate-600',
)

export function BudgetEditor({
  budget,
  onSave,
  onCancel,
}: {
  budget: ProjectBudget
  onSave: (projectId: string, update: BudgetSettingsUpdate) => void
  onCancel: () => void
}) {
  const [dailyLimit, setDailyLimit] = useState<string>(
    budget.daily.limit !== null ? String(budget.daily.limit) : '',
  )
  const [monthlyLimit, setMonthlyLimit] = useState<string>(
    budget.monthly.limit !== null ? String(budget.monthly.limit) : '',
  )
  const [alertThreshold, setAlertThreshold] = useState<string>('0.8')

  const handleSave = () => {
    const update: BudgetSettingsUpdate = {
      daily_cost_budget_usd: dailyLimit ? parseFloat(dailyLimit) : null,
      monthly_cost_budget_usd: monthlyLimit ? parseFloat(monthlyLimit) : null,
      budget_alert_threshold: alertThreshold
        ? parseFloat(alertThreshold)
        : null,
    }
    onSave(budget.project_id, update)
  }

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
            className={INPUT_BASE}
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
            className={INPUT_BASE}
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
            className={cn(INPUT_BASE, 'w-16')}
          />
        </div>
        <div className="flex items-center gap-2 ml-auto">
          <button
            type="button"
            onClick={handleSave}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium',
              'bg-emerald-600/20 text-emerald-400 border border-emerald-600/30',
              'hover:bg-emerald-600/30 transition-colors',
            )}
          >
            <Check className="h-3.5 w-3.5" />
            Save
          </button>
          <button
            type="button"
            onClick={onCancel}
            className={cn(
              'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-sm font-medium',
              'bg-slate-700/30 text-slate-400 border border-slate-700/50',
              'hover:bg-slate-700/50 transition-colors',
            )}
          >
            <X className="h-3.5 w-3.5" />
            Cancel
          </button>
        </div>
      </div>
    </td>
  )
}
