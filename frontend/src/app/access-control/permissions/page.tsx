'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { FolderLock, Plus } from 'lucide-react'
import { type FormEvent, useCallback, useState } from 'react'
import {
  createProjectPermission,
  fetchProjectPermissions,
  type ProjectPermission,
  type ProjectPermissionCreate,
} from '@/lib/api'
import { PermissionRow } from './_components/PermissionRow'

// ─── Permissions table ────────────────────────────────────────────────────────

function PermissionsTable({
  permissions,
}: {
  permissions: ProjectPermission[]
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-slate-800/80">
      <table className="w-full">
        <thead className="bg-slate-800/50">
          <tr>
            {['Project', 'Automations', 'Updated'].map((col) => (
              <th
                key={col}
                className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-slate-400"
              >
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-800/50">
          {permissions.map((p) => (
            <PermissionRow key={p.project_id} permission={p} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AddProjectPermissionForm({
  onCreate,
  isPending,
}: {
  onCreate: (payload: ProjectPermissionCreate) => void
  isPending: boolean
}) {
  const [projectId, setProjectId] = useState('')

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const normalized = projectId.trim()
    if (!normalized) return
    onCreate({ project_id: normalized })
    setProjectId('')
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="mb-4 rounded-lg border border-slate-800/80 bg-slate-900/40 p-4"
    >
      <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
        <label className="flex min-w-0 flex-1 flex-col gap-1.5 text-xs text-slate-400">
          Project ID
          <input
            value={projectId}
            onChange={(event) => setProjectId(event.target.value)}
            placeholder="test2"
            className="h-10 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 outline-none ring-0 placeholder:text-slate-500"
          />
        </label>
        <button
          type="submit"
          disabled={isPending || projectId.trim().length === 0}
          className="inline-flex h-10 items-center justify-center gap-2 rounded-md bg-slate-100 px-4 text-sm font-medium text-slate-900 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Plus className="h-4 w-4" />
          Add Project
        </button>
      </div>
    </form>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ProjectPermissionsPage() {
  const queryClient = useQueryClient()
  const [createError, setCreateError] = useState<string | null>(null)

  const {
    data: permissions,
    isLoading,
    error,
  } = useQuery({
    queryKey: ['project-permissions'],
    queryFn: fetchProjectPermissions,
    refetchInterval: 30000,
  })

  const createMutation = useMutation({
    mutationFn: createProjectPermission,
    onSuccess: () => {
      setCreateError(null)
      queryClient.invalidateQueries({ queryKey: ['project-permissions'] })
    },
    onError: () => {
      setCreateError('Failed to create project permission')
    },
  })

  const handleCreate = useCallback(
    (payload: ProjectPermissionCreate) => {
      setCreateError(null)
      createMutation.mutate(payload)
    },
    [createMutation],
  )

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <FolderLock className="h-5 w-5 text-slate-400" />
            <h1 className="text-base font-semibold text-slate-100">
              Project Permissions
            </h1>
            {permissions && (
              <span className="text-xs text-slate-500">
                ({permissions.length})
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-6">
        {error && (
          <div className="mb-4 p-3 rounded-lg bg-red-900/20 border border-red-800/50">
            <p className="text-sm text-red-400">
              Failed to load project permissions
            </p>
          </div>
        )}
        <AddProjectPermissionForm
          onCreate={handleCreate}
          isPending={createMutation.isPending}
        />
        {createError && (
          <div className="mb-4 rounded-lg border border-red-800/50 bg-red-900/20 p-3">
            <p className="text-sm text-red-400">{createError}</p>
          </div>
        )}

        {isLoading ? (
          <div className="space-y-2">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="h-14 rounded-xl animate-shimmer" />
            ))}
          </div>
        ) : permissions?.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-slate-400">
            <FolderLock className="h-12 w-12 mb-4 opacity-40" />
            <p className="text-lg mb-1">No project permissions configured</p>
            <p className="text-xs text-slate-500">
              Run the migration to seed default permissions
            </p>
          </div>
        ) : permissions ? (
          <PermissionsTable permissions={permissions} />
        ) : null}
      </main>
    </div>
  )
}
