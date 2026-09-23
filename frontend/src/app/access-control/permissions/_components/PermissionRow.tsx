'use client'

import { useCallback, useState } from 'react'
import type { ProjectPermission, ProjectPermissionUpdate } from '@/lib/api'
import { formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import { SaveFlash } from './SaveFlash'
import { TierSelect } from './TierSelect'
import { normalizeTier, TIER_CONFIG } from './tier-config'

export function PermissionRow({
  permission,
  onUpdate,
}: {
  permission: ProjectPermission
  onUpdate: (projectId: string, update: ProjectPermissionUpdate) => void
}) {
  const [savingField, setSavingField] = useState<string | null>(null)
  const [errorField, setErrorField] = useState<string | null>(null)
  const tier = normalizeTier(permission.permission_tier)
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

      {/* Automations */}
      <td className="px-4 py-3.5">
        <a
          href={`/automations?project_id=${encodeURIComponent(permission.project_id)}`}
          aria-label={`Manage ${permission.project_id} automations`}
          className="text-sm text-amber-300 hover:underline"
        >
          Manage
        </a>
      </td>

      {/* Updated */}
      <td className="px-4 py-3.5 text-sm text-slate-500">
        {formatRelativeTime(permission.updated_at)}
      </td>
    </tr>
  )
}
