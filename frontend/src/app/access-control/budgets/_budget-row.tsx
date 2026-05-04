'use client'

import { Pencil } from 'lucide-react'
import { useCallback, useState } from 'react'
import type { BudgetSettingsUpdate, ProjectBudget } from '@/lib/api'
import { cn } from '@/lib/utils'
import { BudgetEditor } from './_budget-editor'
import { AlertBadge, BudgetBar, SaveFlash } from './_components'

export function BudgetRow({
  budget,
  isEditing,
  onEdit,
  onCancelEdit,
  onSave,
}: {
  budget: ProjectBudget
  isEditing: boolean
  onEdit: () => void
  onCancelEdit: () => void
  onSave: (projectId: string, update: BudgetSettingsUpdate) => void
}) {
  const [savingField, setSavingField] = useState<string | null>(null)
  const [errorField] = useState<string | null>(null)

  const handleSave = useCallback(
    (projectId: string, update: BudgetSettingsUpdate) => {
      setSavingField('budget')
      onSave(projectId, update)
      setTimeout(() => setSavingField(null), 1200)
    },
    [onSave],
  )

  const dotColor =
    budget.alert_level === 'critical'
      ? 'bg-red-500'
      : budget.alert_level === 'warning'
        ? 'bg-amber-500'
        : 'bg-emerald-500'

  if (isEditing) {
    return (
      <tr className="bg-slate-800/10">
        <BudgetEditor
          budget={budget}
          onSave={(pid, update) => {
            handleSave(pid, update)
            onCancelEdit()
          }}
          onCancel={onCancelEdit}
        />
      </tr>
    )
  }

  return (
    <tr className="group hover:bg-slate-800/20 transition-colors">
      {/* Project */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div className={cn('w-1 h-8 rounded-full flex-shrink-0', dotColor)} />
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
            saving={savingField === 'budget'}
            error={errorField === 'budget'}
          />
        </div>
      </td>

      {/* Actions */}
      <td className="px-4 py-3.5">
        <button
          type="button"
          onClick={onEdit}
          className={cn(
            'flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium',
            'text-slate-400 border border-slate-700/60 bg-slate-800/40',
            'hover:text-slate-200 hover:bg-slate-800 hover:border-slate-600',
            'opacity-0 group-hover:opacity-100 transition-all',
          )}
        >
          <Pencil className="h-3 w-3" />
          Edit
        </button>
      </td>
    </tr>
  )
}
