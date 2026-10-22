import type { WorkRoleOption } from '@/lib/api/duration-split'
import { accountingWindowForHours } from '../hooks/useSessionListState'
import type { SessionListState } from '../types'

const control =
  'max-w-full h-8 rounded-md border border-slate-700 bg-slate-950 px-2 text-xs text-slate-200 focus-ring-amber'

export function AccountingControls({
  state,
  roles,
  harnesses = [],
  onChange,
}: {
  state: SessionListState
  roles: WorkRoleOption[]
  harnesses?: WorkRoleOption[]
  onChange: (patch: Partial<SessionListState>) => void
}) {
  const hours = state.accountingWindow
    ? (Date.parse(state.accountingWindow.end) -
        Date.parse(state.accountingWindow.start)) /
      3_600_000
    : 24
  return (
    <>
      <label className="flex min-w-0 items-center gap-1.5 text-xs text-slate-400">
        <span>Accounting window</span>
        <select
          className={control}
          value={[1, 24, 168].includes(hours) ? hours : 'custom'}
          onChange={(event) =>
            onChange({
              accountingWindow: accountingWindowForHours(
                Number(event.target.value),
              ),
            })
          }
        >
          {![1, 24, 168].includes(hours) && (
            <option value="custom">Custom interval</option>
          )}
          <option value="1">Last hour</option>
          <option value="24">Last day</option>
          <option value="168">Last week</option>
        </select>
      </label>
      <RegistryFilter
        label="Work role"
        value={state.workRole}
        options={roles}
        onChange={(workRole) => onChange({ workRole })}
      />
      <RegistryFilter
        label="Harness"
        value={state.harness}
        options={harnesses}
        onChange={(harness) => onChange({ harness })}
      />
    </>
  )
}

function RegistryFilter({
  label,
  value,
  options,
  onChange,
}: {
  label: string
  value: string
  options: WorkRoleOption[]
  onChange: (value: string) => void
}) {
  return (
    <label className="flex min-w-0 items-center gap-1.5 text-xs text-slate-400">
      <span>{label}</span>
      <select
        className={control}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      >
        <option value="">All</option>
        {value && !options.some((option) => option.id === value) && (
          <option value={value}>{value}</option>
        )}
        {options.map((option) => (
          <option key={option.id} value={option.id}>
            {option.label}
          </option>
        ))}
      </select>
    </label>
  )
}

export function AccountingWindowLabel({
  window,
}: {
  window: SessionListState['accountingWindow']
}) {
  if (!window)
    return (
      <p className="text-xs text-slate-400">Accounting interval unavailable.</p>
    )
  return (
    <p className="text-xs text-slate-400 break-words">
      Accounting interval:{' '}
      <time dateTime={window.start}>
        {new Date(window.start).toLocaleString()}
      </time>{' '}
      –{' '}
      <time dateTime={window.end}>{new Date(window.end).toLocaleString()}</time>
      . Admin and Other estimate tool text added once. Other includes
      substantive + unknown. Missing or truncated output has unknown size.
      Prose, system instructions, repeated context reads and compaction are
      excluded; resident context is unavailable here. Provider usage is
      cumulative.
    </p>
  )
}
