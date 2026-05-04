'use client'

import { useCallback, useState } from 'react'
import type { ProjectPermission, ProjectPermissionUpdate } from '@/lib/api'
import { formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import { HourSelect } from './HourSelect'
import { SaveFlash } from './SaveFlash'
import { TierSelect } from './TierSelect'
import { Toggle } from './Toggle'
import { TIER_CONFIG, type Tier } from './tier-config'

export function PermissionRow({
  permission,
  onUpdate,
}: {
  permission: ProjectPermission
  onUpdate: (projectId: string, update: ProjectPermissionUpdate) => void
}) {
  const [savingField, setSavingField] = useState<string | null>(null)
  const [errorField, setErrorField] = useState<string | null>(null)
  const tier = permission.permission_tier as Tier
  const tierConfig = TIER_CONFIG[tier]

  const handleUpdate = useCallback(
    (field: string, update: ProjectPermissionUpdate) => {
      setSavingField(field)
      setErrorField(null)
      onUpdate(permission.project_id, update)
      setTimeout(() => setSavingField(null), 1200)
    },
    [permission.project_id, onUpdate],
  )

  return (
    <tr className="group hover:bg-slate-800/20 transition-colors">
      {/* Project */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-3">
          <div
            className={cn('w-1 h-8 rounded-full flex-shrink-0', tierConfig.dot)}
          />
          <div>
            <p className="text-sm font-semibold text-slate-100">
              {permission.project_id}
            </p>
            {permission.root_path && (
              <p className="text-[11px] text-slate-500 font-mono truncate max-w-[220px]">
                {permission.root_path}
              </p>
            )}
          </div>
        </div>
      </td>

      {/* Tier */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <TierSelect
            value={tier}
            onChange={(newTier) =>
              handleUpdate('tier', { permission_tier: newTier })
            }
          />
          <SaveFlash
            saving={savingField === 'tier'}
            error={errorField === 'tier'}
          />
        </div>
      </td>

      {/* Auto Exec */}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          <Toggle
            checked={permission.auto_exec_enabled}
            onChange={(v) => handleUpdate('exec', { auto_exec_enabled: v })}
            disabled={tier === 'off'}
            label={`Auto-exec for ${permission.project_id}`}
          />
          {tier === 'off' && (
            <span className="text-[10px] text-slate-600">N/A</span>
          )}
          <SaveFlash
            saving={savingField === 'exec'}
            error={errorField === 'exec'}
          />
        </div>
      </td>

      {/* Execution Window */}
      <td className="px-4 py-3.5">
        {permission.auto_exec_enabled && tier !== 'off' ? (
          <div className="flex items-center gap-1.5">
            <HourSelect
              value={permission.execution_start_hour}
              onChange={(v) =>
                handleUpdate('hours', { execution_start_hour: v })
              }
            />
            <span className="text-slate-600 text-xs">&ndash;</span>
            <HourSelect
              value={permission.execution_end_hour}
              onChange={(v) => handleUpdate('hours', { execution_end_hour: v })}
            />
            <SaveFlash
              saving={savingField === 'hours'}
              error={errorField === 'hours'}
            />
          </div>
        ) : (
          <span className="text-xs text-slate-600">
            {tier === 'off' ? 'Disabled' : 'Exec off'}
          </span>
        )}
      </td>

      {/* Updated */}
      <td className="px-4 py-3.5 text-sm text-slate-500">
        {formatRelativeTime(permission.updated_at)}
      </td>
    </tr>
  )
}
