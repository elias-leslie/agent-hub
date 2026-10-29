'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { KeyRound, Plus } from 'lucide-react'
import { useMemo, useState } from 'react'
import {
  SortableHeader,
  type SortDirection,
} from '@/components/ui/SortableHeader'
import {
  type AgentLogin,
  addAccountLogin,
  editAgentLogin,
  fetchAgentLogins,
  removeAgentLogin,
  replaceAgentLogin,
} from '@/lib/api/lab-credentials'
import { formatRelativeTime } from '@/lib/formatters'
import { cn } from '@/lib/utils'
import {
  type FormMode,
  type FormResult,
  LoginForm,
} from './_components/LoginForm'
import {
  fieldSummary,
  filterLogins,
  type KindFilter,
  kindLabel,
  loginStatus,
  type SortField,
  safeLoginUrl,
  sortLogins,
} from './_components/loginView'

const COLUMNS: { field: SortField; label: string }[] = [
  { field: 'target', label: 'Site' },
  { field: 'actor', label: 'Actor' },
  { field: 'kind', label: 'Type' },
  { field: 'fields', label: 'Fields' },
  { field: 'login_url', label: 'Login URL' },
  { field: 'status', label: 'Status' },
  { field: 'updated_at', label: 'Updated' },
]

const KIND_OPTIONS: { value: KindFilter; label: string }[] = [
  { value: 'all', label: 'All types' },
  { value: 'account', label: 'Real logins' },
  { value: 'synthetic', label: 'Test logins' },
  { value: 'temporary', label: 'Temporary' },
  { value: 'unreadable', label: 'Unreadable' },
]

const buttonClass =
  'rounded px-2 py-1 text-xs text-slate-300 transition-colors hover:bg-slate-800 hover:text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60'

function formatDate(iso: string) {
  return new Date(iso).toLocaleString('en-US', {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function StatusChip({ login }: { login: AgentLogin }) {
  const status = loginStatus(login)
  const tone =
    status.state === 'unreadable' || status.state === 'expired'
      ? 'border-red-500/40 bg-red-500/10 text-red-700 dark:text-red-300'
      : status.state === 'expires'
        ? 'border-amber-500/40 bg-amber-500/10 text-amber-800 dark:text-amber-300'
        : 'border-slate-700 bg-slate-800/60 text-slate-300'
  const text =
    status.state === 'unreadable'
      ? "Can't be read"
      : status.state === 'expired'
        ? `Expired ${formatDate(status.at)}`
        : status.state === 'expires'
          ? `Expires ${formatDate(status.at)}`
          : 'No expiry'
  return (
    <span
      className={cn(
        'inline-block rounded-full border px-2 py-0.5 text-xs whitespace-nowrap',
        tone,
      )}
    >
      {text}
    </span>
  )
}

function LoginRow({
  login,
  confirming,
  busy,
  onAction,
}: {
  login: AgentLogin
  confirming: boolean
  busy: boolean
  onAction: (action: 'edit' | 'replace' | 'remove' | 'confirm' | 'keep') => void
}) {
  const url = safeLoginUrl(login.login_url)
  const editable = !login.undecodable && login.kind !== 'temporary'
  const name = `${login.target} / ${login.actor}`
  return (
    <tr className="align-top transition-colors hover:bg-slate-800/20">
      <td className="px-4 py-3 text-sm font-semibold text-slate-100">
        {login.target}
      </td>
      <td className="px-4 py-3 text-sm text-slate-300">{login.actor}</td>
      <td className="px-4 py-3 text-sm text-slate-300">{kindLabel(login)}</td>
      <td className="px-4 py-3 text-sm text-slate-400">
        {login.undecodable ? (
          <span className="text-slate-500">Unknown</span>
        ) : (
          fieldSummary(login)
        )}
      </td>
      <td className="max-w-[220px] px-4 py-3 text-sm">
        {url ? (
          <a
            href={url.href}
            target="_blank"
            rel="noreferrer noopener"
            title={url.href}
            className="block truncate text-amber-700 hover:underline dark:text-amber-300"
          >
            {url.host}
          </a>
        ) : login.login_url ? (
          <span className="block truncate text-slate-400">
            {login.login_url}
          </span>
        ) : (
          <span className="text-slate-500">Not set</span>
        )}
      </td>
      <td className="px-4 py-3">
        <StatusChip login={login} />
      </td>
      <td
        className="px-4 py-3 text-sm whitespace-nowrap text-slate-500"
        title={login.updated_at ? formatDate(login.updated_at) : undefined}
      >
        {login.updated_at ? formatRelativeTime(login.updated_at) : 'Unknown'}
      </td>
      <td className="px-4 py-3">
        {confirming ? (
          <div className="flex flex-wrap items-center gap-1">
            <span className="text-xs text-slate-300">
              Remove {name}? Agents lose it.
            </span>
            <button
              type="button"
              disabled={busy}
              onClick={() => onAction('confirm')}
              aria-label={`Confirm remove ${name}`}
              className="rounded bg-red-500/15 px-2 py-1 text-xs text-red-700 hover:bg-red-500/25 dark:text-red-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-500/60"
            >
              Remove
            </button>
            <button
              type="button"
              onClick={() => onAction('keep')}
              className={buttonClass}
            >
              Keep
            </button>
          </div>
        ) : (
          <div className="flex gap-1">
            {editable && (
              <>
                <button
                  type="button"
                  onClick={() => onAction('edit')}
                  aria-label={`Edit ${name}`}
                  className={buttonClass}
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => onAction('replace')}
                  aria-label={`Replace ${name}`}
                  className={buttonClass}
                >
                  Replace
                </button>
              </>
            )}
            <button
              type="button"
              onClick={() => onAction('remove')}
              aria-label={`Remove ${name}`}
              className={cn(
                buttonClass,
                'hover:text-red-700 dark:hover:text-red-300',
              )}
            >
              Remove
            </button>
          </div>
        )}
      </td>
    </tr>
  )
}

type Panel = { mode: FormMode; login: AgentLogin | null } | null

export default function AgentLoginsPage() {
  const queryClient = useQueryClient()
  const [text, setText] = useState('')
  const [kind, setKind] = useState<KindFilter>('all')
  const [showExpired, setShowExpired] = useState(true)
  const [sort, setSort] = useState<{
    field: SortField
    direction: SortDirection
  }>({
    field: 'target',
    direction: 'asc',
  })
  const [panel, setPanel] = useState<Panel>(null)
  const [formError, setFormError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState<string | null>(null)
  const [removeError, setRemoveError] = useState<string | null>(null)

  const { data, isLoading, error, refetch, dataUpdatedAt } = useQuery({
    queryKey: ['agent-logins'],
    queryFn: fetchAgentLogins,
  })

  const refresh = () =>
    queryClient.invalidateQueries({ queryKey: ['agent-logins'] })

  const save = useMutation({
    mutationFn: async ({
      panel: { mode, login },
      form,
    }: {
      panel: NonNullable<Panel>
      form: FormResult
    }) => {
      if (mode === 'add') {
        const { username, password, login_url, totp_secret } = form.values
        return addAccountLogin({
          target: form.target,
          actor: form.actor,
          username,
          password,
          login_url,
          ...(totp_secret ? { totp_secret } : {}),
        })
      }
      if (!login) return
      if (mode === 'edit') {
        return editAgentLogin(login.target, login.actor, {
          set: form.values,
          remove: form.remove,
          ...(form.expiresAt !== undefined
            ? { expires_at: form.expiresAt }
            : {}),
        })
      }
      const expiry = form.expiresAt ? { expires_at: form.expiresAt } : {}
      return replaceAgentLogin(
        login.target,
        login.actor,
        login.kind === 'account'
          ? { ...form.values, ...expiry }
          : { values: form.values, ...expiry },
      )
    },
    onSuccess: () => {
      setPanel(null)
      setFormError(null)
      refresh()
    },
    onError: (err: Error) => setFormError(err.message),
  })

  const remove = useMutation({
    mutationFn: (login: AgentLogin) =>
      removeAgentLogin(login.target, login.actor),
    onSuccess: () => {
      setConfirming(null)
      setRemoveError(null)
      refresh()
    },
    onError: (err: Error) => setRemoveError(err.message),
  })

  const logins = data ?? []
  const visible = useMemo(
    () =>
      sortLogins(
        filterLogins(logins, { text, kind, showExpired }),
        sort.field,
        sort.direction,
      ),
    [logins, text, kind, showExpired, sort],
  )
  const unreadable = logins.filter((login) => login.undecodable).length
  const filtering = text.trim() !== '' || kind !== 'all' || !showExpired

  const openPanel = (next: Panel) => {
    setFormError(null)
    setPanel(next)
  }

  const act = (login: AgentLogin, action: string) => {
    setRemoveError(null)
    if (action === 'edit' || action === 'replace')
      openPanel({ mode: action, login })
    else if (action === 'remove') setConfirming(login.reference)
    else if (action === 'keep') setConfirming(null)
    else remove.mutate(login)
  }

  const clearFilters = () => {
    setText('')
    setKind('all')
    setShowExpired(true)
  }

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <header className="page-header">
        <div className="page-header-row px-4 lg:px-8">
          <div className="page-title-group">
            <div className="page-title-icon">
              <KeyRound className="h-5 w-5" />
            </div>
            <h1 className="page-title">Agent logins</h1>
            {data && (
              <span className="text-xs text-slate-500">({logins.length})</span>
            )}
          </div>
          <button
            type="button"
            onClick={() => openPanel({ mode: 'add', login: null })}
            className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-100 px-3 text-sm font-medium text-slate-900"
          >
            <Plus className="h-4 w-4" />
            Add login
          </button>
        </div>
      </header>

      <main className="page-frame">
        <div className="page-container">
          <p className="mb-4 text-sm text-slate-400">
            Logins lent to agents and the test logins labs use. Passwords and
            secrets are never shown here.
          </p>

          {panel && (
            <LoginForm
              key={`${panel.mode}:${panel.login?.reference ?? 'new'}`}
              mode={panel.mode}
              login={panel.login}
              isPending={save.isPending}
              error={formError}
              onSubmit={(form) => save.mutate({ panel, form })}
              onCancel={() => setPanel(null)}
            />
          )}

          {error && data && (
            <div
              role="alert"
              className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300"
            >
              Could not refresh. Showing the list from{' '}
              {formatDate(new Date(dataUpdatedAt).toISOString())}.{' '}
              <button
                type="button"
                onClick={() => refetch()}
                className="underline"
              >
                Try again
              </button>
            </div>
          )}
          {unreadable > 0 && (
            <div
              role="status"
              className="mb-4 rounded-lg border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-800 dark:text-amber-300"
            >
              {unreadable === 1
                ? "1 login can't be read, so its type and fields are unknown."
                : `${unreadable} logins can't be read, so their types and fields are unknown.`}{' '}
              You can still remove {unreadable === 1 ? 'it' : 'them'}.
            </div>
          )}
          {removeError && (
            <p
              role="alert"
              className="mb-4 text-sm text-red-700 dark:text-red-400"
            >
              {removeError}
            </p>
          )}

          {isLoading ? (
            <div
              role="status"
              aria-label="Loading logins"
              className="space-y-2"
            >
              {[1, 2, 3, 4].map((i) => (
                <div key={i} className="h-12 rounded-xl animate-shimmer" />
              ))}
            </div>
          ) : error && !data ? (
            <div
              role="alert"
              className="rounded-lg border border-red-500/40 bg-red-500/10 p-4"
            >
              <p className="text-sm text-red-700 dark:text-red-400">
                Could not load agent logins.
              </p>
              <p className="mt-1 text-xs text-slate-400">{error.message}</p>
              <button
                type="button"
                onClick={() => refetch()}
                className="mt-3 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
              >
                Try again
              </button>
            </div>
          ) : logins.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-400">
              <KeyRound className="mb-4 h-12 w-12 opacity-40" />
              <p className="mb-1 text-lg">No agent logins yet</p>
              <p className="text-xs text-slate-500">
                Add a real login to lend it to agents. Test logins appear when a
                lab creates them.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-end gap-3">
                <label className="flex min-w-[200px] flex-1 flex-col gap-1 text-xs text-slate-400">
                  Search
                  <input
                    type="search"
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder="Site, actor, field or URL"
                    className="h-9 rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
                  />
                </label>
                <label className="flex flex-col gap-1 text-xs text-slate-400">
                  Type
                  <select
                    value={kind}
                    onChange={(event) =>
                      setKind(event.target.value as KindFilter)
                    }
                    className="h-9 rounded-md border border-slate-700 bg-slate-950 px-2 text-sm text-slate-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60"
                  >
                    {KIND_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="flex h-9 items-center gap-2 text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={showExpired}
                    onChange={(event) => setShowExpired(event.target.checked)}
                  />
                  Show expired
                </label>
                <p
                  className="ml-auto text-xs text-slate-500"
                  aria-live="polite"
                >
                  Showing {visible.length} of {logins.length}
                </p>
              </div>

              {visible.length === 0 ? (
                <div className="rounded-lg border border-slate-800/80 p-8 text-center text-slate-400">
                  <p className="text-sm">No logins match these filters.</p>
                  {filtering && (
                    <button
                      type="button"
                      onClick={clearFilters}
                      className="mt-3 rounded-md border border-slate-700 px-3 py-1.5 text-sm text-slate-200 hover:bg-slate-800"
                    >
                      Clear filters
                    </button>
                  )}
                </div>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-slate-800/80">
                  <table className="w-full min-w-[960px]">
                    <thead className="bg-slate-800/50">
                      <tr>
                        {COLUMNS.map((column) => (
                          <th
                            key={column.field}
                            scope="col"
                            aria-sort={
                              sort.field === column.field
                                ? sort.direction === 'asc'
                                  ? 'ascending'
                                  : 'descending'
                                : 'none'
                            }
                            className="px-4 py-3 text-left"
                          >
                            <SortableHeader
                              label={column.label}
                              field={column.field}
                              currentField={sort.field}
                              direction={sort.direction}
                              onSort={(field) =>
                                setSort((current) => ({
                                  field,
                                  direction:
                                    current.field === field &&
                                    current.direction === 'asc'
                                      ? 'desc'
                                      : 'asc',
                                }))
                              }
                            />
                          </th>
                        ))}
                        <th
                          scope="col"
                          className="px-4 py-3 text-left text-[10px] font-bold tracking-wider text-slate-500 uppercase"
                        >
                          Actions
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-800/50">
                      {visible.map((login, index) => (
                        <LoginRow
                          // Duplicate references are possible; position keeps rows distinct.
                          key={`${login.reference}:${index}`}
                          login={login}
                          confirming={confirming === login.reference}
                          busy={remove.isPending}
                          onAction={(action) => act(login, action)}
                        />
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </div>
      </main>
    </div>
  )
}
