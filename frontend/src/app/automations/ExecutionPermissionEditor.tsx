'use client'

import { useState } from 'react'
import type {
  ProjectPermission,
  ProjectPermissionUpdate,
} from '@/lib/api/project-permissions'

export function ExecutionPermissionEditor({
  permission,
  saving,
  onSave,
}: {
  permission: ProjectPermission
  saving: boolean
  onSave: (update: ProjectPermissionUpdate) => void
}) {
  const [enabled, setEnabled] = useState(permission.auto_exec_enabled)
  const [startHour, setStartHour] = useState(permission.execution_start_hour)
  const [endHour, setEndHour] = useState(permission.execution_end_hour)
  const changed =
    enabled !== permission.auto_exec_enabled ||
    startHour !== permission.execution_start_hour ||
    endHour !== permission.execution_end_hour
  const tierOff = permission.permission_tier === 'off'

  return (
    <form
      className="section-card space-y-5"
      onSubmit={(event) => {
        event.preventDefault()
        onSave({
          auto_exec_enabled: enabled,
          execution_start_hour: startHour,
          execution_end_hour: endHour,
        })
      }}
    >
      <div>
        <h2 className="section-heading">Execution permission</h2>
        <p className="section-copy mt-1">
          Controls automated project work that checks execution permission.
        </p>
      </div>
      <p className="text-sm text-slate-400">
        Access tier:{' '}
        <span className="capitalize text-slate-200">
          {permission.permission_tier}
        </span>
      </p>
      {tierOff && (
        <p className="text-sm text-amber-300">
          The Off access tier blocks automated execution. Change the tier in{' '}
          <a href="/access-control/permissions" className="underline">
            Access Control
          </a>{' '}
          first.
        </p>
      )}
      <label className="flex items-center gap-3 text-sm font-medium text-slate-200">
        <input
          type="checkbox"
          checked={enabled}
          disabled={tierOff}
          onChange={(event) => setEnabled(event.target.checked)}
          className="h-4 w-4 accent-amber-500"
        />
        Allow automated execution
      </label>
      <div className="flex flex-wrap gap-4">
        <label className="text-sm text-slate-300">
          Start hour
          <select
            className="control-select mt-1 block"
            value={startHour}
            disabled={tierOff}
            onChange={(event) => setStartHour(Number(event.target.value))}
          >
            {Array.from({ length: 24 }, (_, hour) => (
              <option
                key={hour}
                value={hour}
              >{`${String(hour).padStart(2, '0')}:00`}</option>
            ))}
          </select>
        </label>
        <label className="text-sm text-slate-300">
          End hour
          <select
            className="control-select mt-1 block"
            value={endHour}
            disabled={tierOff}
            onChange={(event) => setEndHour(Number(event.target.value))}
          >
            {Array.from({ length: 24 }, (_, index) => index + 1).map((hour) => (
              <option
                key={hour}
                value={hour}
              >{`${String(hour).padStart(2, '0')}:00`}</option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="submit"
        disabled={!changed || saving || tierOff || startHour === endHour}
        className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {saving ? 'Saving…' : 'Save execution permission'}
      </button>
    </form>
  )
}
