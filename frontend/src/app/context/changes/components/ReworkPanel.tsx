'use client'

import { useQuery } from '@tanstack/react-query'
import { useId, useState } from 'react'
import type { Edit, Narrow, QueueRow } from '@/lib/api/context-changes'
import { fetchSessionFacets } from '@/lib/api/sessions'
import { cn } from '@/lib/utils'

type Mode = 'narrow' | 'edit'
type Target = 'project' | 'role' | 'session'

const asText = (value: unknown) => (typeof value === 'string' ? value : '')

/** Inline rework: narrow who gets it, or edit the text. Sends only what the owner changed. */
export function ReworkPanel({
  row,
  busy,
  onSubmit,
  onCancel,
}: {
  row: QueueRow
  busy: boolean
  onSubmit: (change: { narrow: Narrow } | { edit: Edit }) => void
  onCancel: () => void
}) {
  const id = useId()
  const writer = row.writers.find((w) => w.project || w.work_role)
  const [mode, setMode] = useState<Mode>('narrow')
  const [target, setTarget] = useState<Target>(
    writer?.project ? 'project' : writer?.work_role ? 'role' : 'session',
  )
  const [project, setProject] = useState(writer?.project ?? '')
  const [role, setRole] = useState(writer?.work_role ?? '')
  const content0 = asText(row.after?.content)
  const name0 = asText(row.after?.name)
  const summary0 = asText(row.after?.summary)
  const [content, setContent] = useState(content0)
  const [name, setName] = useState(name0)
  const [summary, setSummary] = useState(summary0)

  const facets = useQuery({
    queryKey: ['context-changes-facets'],
    queryFn: () => fetchSessionFacets({}),
    staleTime: 10 * 60_000,
    retry: false,
  })
  const roles = (facets.data?.work_roles ?? []).filter(
    (r) => r.id !== 'unknown',
  )
  const projects = facets.data?.projects ?? []

  const edit: Edit = {
    ...(content !== content0 && { content }),
    ...(name !== name0 && { name }),
    ...(summary !== summary0 && { summary }),
  }
  const editReady = Object.keys(edit).length > 0 && content.trim() !== ''
  const narrow: Narrow | null =
    target === 'session'
      ? { to: 'session' }
      : target === 'project' && project.trim()
        ? { to: 'project', project_id: project.trim() }
        : target === 'role' && role.trim()
          ? { to: 'role', role: role.trim() }
          : null
  const canEdit = row.after != null && row.target_kind !== 'placement'

  return (
    <div className="mt-2 space-y-3 rounded-lg border border-slate-700/70 bg-slate-950/60 p-3">
      <div role="group" aria-label="Rework how" className="flex gap-1">
        {(['narrow', 'edit'] as const).map((m) => (
          <button
            key={m}
            type="button"
            aria-pressed={mode === m}
            disabled={m === 'edit' && !canEdit}
            onClick={() => setMode(m)}
            className={cn(
              'h-8 rounded-lg px-3 text-xs font-semibold focus-ring-amber disabled:opacity-40',
              mode === m
                ? 'bg-slate-700 text-amber-200'
                : 'text-slate-400 hover:bg-slate-800',
            )}
          >
            {m === 'narrow' ? 'Narrow' : 'Edit'}
          </button>
        ))}
      </div>

      {mode === 'narrow' ? (
        <fieldset className="space-y-2 text-sm text-slate-200">
          <legend className="mb-1 text-xs text-slate-400">
            Who should get it instead
          </legend>
          <label className="flex flex-wrap items-center gap-2">
            <input
              type="radio"
              name={`${id}-t`}
              checked={target === 'project'}
              onChange={() => setTarget('project')}
              className="accent-amber-500"
            />
            <span>One project</span>
            <input
              aria-label="Project"
              list={`${id}-projects`}
              value={project}
              disabled={target !== 'project'}
              onChange={(e) => setProject(e.target.value)}
              placeholder="project id"
              className="control-input h-8 w-full max-w-56 py-0 text-xs"
            />
            <datalist id={`${id}-projects`}>
              {projects.map((p) => (
                <option key={p.project_id} value={p.project_id} />
              ))}
            </datalist>
          </label>
          <label className="flex flex-wrap items-center gap-2">
            <input
              type="radio"
              name={`${id}-t`}
              checked={target === 'role'}
              onChange={() => setTarget('role')}
              className="accent-amber-500"
            />
            <span>One role</span>
            {roles.length > 0 ? (
              <select
                aria-label="Role"
                value={role}
                disabled={target !== 'role'}
                onChange={(e) => setRole(e.target.value)}
                className="control-select h-8 py-0 text-xs"
              >
                <option value="">Pick a role</option>
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                aria-label="Role"
                value={role}
                disabled={target !== 'role'}
                onChange={(e) => setRole(e.target.value)}
                placeholder="role id"
                className="control-input h-8 w-full max-w-56 py-0 text-xs"
              />
            )}
          </label>
          <label className="flex flex-wrap items-center gap-2">
            <input
              type="radio"
              name={`${id}-t`}
              checked={target === 'session'}
              onChange={() => setTarget('session')}
              className="accent-amber-500"
            />
            <span>This session only</span>
            <span className="text-xs text-slate-500">
              archives it, so no later session gets it
            </span>
          </label>
        </fieldset>
      ) : (
        <div className="space-y-2 text-xs text-slate-400">
          {row.target_kind === 'memory' && (
            <label className="block">
              Summary
              <input
                value={summary}
                onChange={(e) => setSummary(e.target.value)}
                className="control-input mt-1 py-1.5 text-xs"
              />
            </label>
          )}
          <label className="block">
            Name
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="control-input mt-1 py-1.5 text-xs"
            />
          </label>
          <label className="block">
            Text
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              rows={Math.min(14, Math.max(4, content.split('\n').length + 1))}
              className="control-input mt-1 font-mono text-xs"
            />
          </label>
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        <button
          type="button"
          disabled={busy || (mode === 'edit' ? !editReady : narrow == null)}
          onClick={() => {
            if (mode === 'edit') onSubmit({ edit })
            else if (narrow) onSubmit({ narrow })
          }}
          className="h-9 rounded-lg bg-amber-500 px-4 text-xs font-semibold text-slate-950 hover:bg-amber-400 focus-ring-amber disabled:opacity-40"
        >
          {busy ? 'Saving…' : mode === 'edit' ? 'Save edit' : 'Save narrowing'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="h-9 rounded-lg border border-slate-700/80 px-3 text-xs text-slate-300 hover:bg-slate-800 focus-ring-amber"
        >
          Cancel
        </button>
      </div>
    </div>
  )
}
