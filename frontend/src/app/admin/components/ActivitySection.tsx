'use client'

import { useQuery } from '@tanstack/react-query'
import Link from 'next/link'
import {
  AccountingControls,
  AccountingWindowLabel,
} from '@/app/sessions/components/AccountingControls'
import {
  sessionScopeParams,
  useSessionListState,
} from '@/app/sessions/hooks/useSessionListState'
import { toFilterQuery } from '@/app/sessions/hooks/useSessionsData'
import { DEFAULT_LIST_STATE } from '@/app/sessions/types'
import { fetchSessionEfficiency } from '@/lib/api/admin'
import { SESSION_KINDS } from '@/lib/api/sessions'
import { ActivityCostPanel } from './ActivityCostPanel'

const DEFAULT_ACTIVITY_STATE = {
  ...DEFAULT_LIST_STATE,
  kinds: [...SESSION_KINDS],
  includeSubagents: true,
  includeBenchmarks: true,
}

export function ActivitySection() {
  const { state, update } = useSessionListState(DEFAULT_ACTIVITY_STATE)
  const params = sessionScopeParams(state)
  const activity = useQuery({
    queryKey: ['session-efficiency', params.toString()],
    queryFn: () => fetchSessionEfficiency(toFilterQuery(state)),
  })
  const projects = activity.data?.by_project ?? []
  return (
    <ActivityCostPanel
      activity={activity.data ?? null}
      isLoading={activity.isLoading}
      error={activity.error instanceof Error ? activity.error.message : null}
      onRetry={() => void activity.refetch()}
      sessionParams={params}
      controls={
        <div className="space-y-2">
          <div className="flex flex-wrap gap-x-4 gap-y-2">
            <AccountingControls
              state={state}
              roles={activity.data?.work_roles ?? []}
              harnesses={activity.data?.harnesses ?? []}
              onChange={update}
            />
            <label className="flex min-w-0 items-center gap-1.5 text-xs text-slate-400">
              <span>Project</span>
              <select
                value={state.project}
                onChange={(event) => update({ project: event.target.value })}
                className="h-8 max-w-[14rem] rounded-md border border-slate-700 bg-slate-950 px-2 text-xs text-slate-200 focus-ring-amber"
              >
                <option value="">All projects</option>
                {state.project &&
                  !projects.some((row) => row.project_id === state.project) && (
                    <option value={state.project}>{state.project}</option>
                  )}
                {projects.map((row) => (
                  <option key={row.project_id} value={row.project_id}>
                    {row.label}
                  </option>
                ))}
              </select>
            </label>
            <Link
              href={`/sessions?${params}`}
              className="self-center text-xs text-amber-300 underline focus-ring-amber"
            >
              Edit session filters
            </Link>
          </div>
          <AccountingWindowLabel window={state.accountingWindow} />
          <p className="text-xs text-slate-400">
            {state.kinds.join(', ')} ·{' '}
            {state.includeSubagents ? 'including sub-agents' : 'root sessions'}{' '}
            ·{' '}
            {state.includeBenchmarks
              ? 'including benchmarks'
              : 'excluding benchmarks'}
            {state.status ? ` · status ${state.status}` : ''}
            {state.model ? ` · model ${state.model}` : ''}
            {state.q ? ` · search “${state.q}”` : ''}
            {state.since !== 'all' ? ` · active ${state.since}` : ''}
          </p>
        </div>
      }
    />
  )
}
