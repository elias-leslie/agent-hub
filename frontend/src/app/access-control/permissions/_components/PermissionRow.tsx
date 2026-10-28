'use client'

import type { ProjectPermission } from '@/lib/api'
import { formatRelativeTime } from '@/lib/formatters'

export function PermissionRow({
  permission,
}: {
  permission: ProjectPermission
}) {
  return (
    <tr className="group hover:bg-slate-800/20 transition-colors">
      {/* Project */}
      <td className="px-4 py-3.5">
        <p className="text-sm font-semibold text-slate-100">
          {permission.project_id}
        </p>
        {permission.root_path && (
          <p className="text-[11px] text-slate-500 font-mono truncate max-w-[220px]">
            {permission.root_path}
          </p>
        )}
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
