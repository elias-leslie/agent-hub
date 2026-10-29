'use client'

import { type FormEvent, useId, useState } from 'react'
import type { AgentLogin } from '@/lib/api/lab-credentials'
import { sameOrigin } from './loginView'

export type FormMode = 'add' | 'edit' | 'replace'

/** What the form hands back; the page turns it into the right API call. */
export interface FormResult {
  target: string
  actor: string
  /** Fields to send: every field for add and replace, only the changed ones for edit. */
  values: Record<string, string>
  remove: string[]
  /** undefined keeps the expiry. */
  expiresAt: string | null | undefined
}

interface FieldSpec {
  name: string
  label: string
  secret: boolean
  optional: boolean
}

const ACCOUNT_FIELDS: FieldSpec[] = [
  { name: 'username', label: 'Username', secret: false, optional: false },
  { name: 'password', label: 'Password', secret: true, optional: false },
  { name: 'login_url', label: 'Login URL', secret: false, optional: false },
  {
    name: 'totp_secret',
    label: '2FA secret (base32 or otpauth:// link)',
    secret: true,
    optional: true,
  },
]

function specFor(login: AgentLogin | null): FieldSpec[] {
  if (!login || login.kind === 'account') return ACCOUNT_FIELDS
  return login.fields.map((name) => ({
    name,
    label: name === 'login_url' ? 'Login URL' : name,
    secret: name !== 'login_url',
    optional: false,
  }))
}

// datetime-local wants local wall time without a zone.
function toLocalInput(iso: string | null): string {
  if (!iso) return ''
  const date = new Date(iso)
  const shifted = new Date(date.getTime() - date.getTimezoneOffset() * 60000)
  return shifted.toISOString().slice(0, 16)
}

const inputClass =
  'h-10 w-full rounded-md border border-slate-700 bg-slate-950 px-3 text-sm text-slate-100 placeholder:text-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/60'

export function LoginForm({
  mode,
  login,
  isPending,
  error,
  onSubmit,
  onCancel,
}: {
  mode: FormMode
  login: AgentLogin | null
  isPending: boolean
  error: string | null
  onSubmit: (result: FormResult) => void
  onCancel: () => void
}) {
  const id = useId()
  const spec = specFor(mode === 'add' ? null : login)
  const original = login?.login_url ?? ''
  const hasExpiry = mode !== 'add' && login?.kind !== 'account'
  const [target, setTarget] = useState(login?.target ?? '')
  const [actor, setActor] = useState(login?.actor ?? 'default')
  const [values, setValues] = useState<Record<string, string>>(
    mode === 'add' ? {} : { login_url: original },
  )
  const [removed, setRemoved] = useState<string[]>([])
  const initialExpiry = toLocalInput(login?.expires_at ?? null)
  const [expiry, setExpiry] = useState(initialExpiry)

  const value = (name: string) => values[name] ?? ''
  const urlMovedWithoutPassword =
    mode === 'edit' &&
    !!original &&
    !!value('login_url').trim() &&
    !sameOrigin(original, value('login_url').trim()) &&
    !value('password')
  const missing =
    mode === 'add' || mode === 'replace'
      ? spec.some((field) => !field.optional && !value(field.name).trim())
      : false
  const incomplete =
    (mode === 'add' && (!target.trim() || !actor.trim())) || missing

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (incomplete || urlMovedWithoutPassword) return
    const filled = Object.fromEntries(
      spec
        .map((field) => [field.name, value(field.name).trim()] as const)
        .filter(([name, text]) => text && !removed.includes(name)),
    )
    let expiresAt: string | null | undefined
    if (hasExpiry && expiry !== initialExpiry) {
      expiresAt = expiry ? new Date(expiry).toISOString() : null
    } else if (mode === 'replace' && login?.expires_at && !login.expired) {
      expiresAt = login.expires_at
    }
    if (mode === 'edit') {
      delete filled.login_url
      if (value('login_url').trim() !== original) {
        filled.login_url = value('login_url').trim()
      }
    }
    onSubmit({
      target: target.trim(),
      actor: actor.trim(),
      values: filled,
      remove: removed,
      expiresAt,
    })
  }

  const title =
    mode === 'add'
      ? 'Add a login'
      : `${mode === 'edit' ? 'Edit' : 'Replace'} ${login?.target} / ${login?.actor}`
  const blank = mode === 'edit' ? 'Leave blank to keep' : ''

  return (
    <form
      onSubmit={submit}
      aria-label={title}
      autoComplete="off"
      className="mb-4 rounded-lg border border-slate-800/80 bg-slate-900/40 p-4"
    >
      <h2 className="text-sm font-semibold text-slate-100">{title}</h2>
      <p className="mt-1 mb-3 text-xs text-slate-400">
        {mode === 'add' &&
          'A real login lent to agents. Agents use it through the browser login; they never see the password.'}
        {mode === 'edit' &&
          'Change only what you fill in. Secret fields left blank keep their saved value.'}
        {mode === 'replace' &&
          'Replaces the whole login. Enter every field again; nothing is kept.'}
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {mode === 'add' && (
          <>
            <label className="flex flex-col gap-1.5 text-xs text-slate-400">
              Site
              <input
                value={target}
                onChange={(event) => setTarget(event.target.value)}
                placeholder="hackerone"
                autoComplete="off"
                spellCheck={false}
                className={inputClass}
              />
            </label>
            <label className="flex flex-col gap-1.5 text-xs text-slate-400">
              Actor
              <input
                value={actor}
                onChange={(event) => setActor(event.target.value)}
                autoComplete="off"
                spellCheck={false}
                className={inputClass}
              />
            </label>
          </>
        )}
        {spec.map((field) => (
          <div key={field.name} className="flex flex-col gap-1.5">
            <label
              htmlFor={`${id}-${field.name}`}
              className="text-xs text-slate-400"
            >
              {field.label}
              {field.optional && mode !== 'edit' ? ' (optional)' : ''}
            </label>
            <input
              id={`${id}-${field.name}`}
              type={field.secret ? 'password' : 'text'}
              autoComplete="off"
              spellCheck={false}
              value={value(field.name)}
              disabled={removed.includes(field.name)}
              onChange={(event) =>
                setValues({ ...values, [field.name]: event.target.value })
              }
              placeholder={
                field.name === 'login_url'
                  ? 'https://example.com/login'
                  : field.secret || field.name === 'username'
                    ? blank
                    : undefined
              }
              className={inputClass}
            />
            {mode === 'edit' &&
              login?.fields.includes(field.name) &&
              (field.optional || login.kind !== 'account') &&
              field.name !== 'login_url' && (
                <label className="flex items-center gap-2 text-xs text-slate-500">
                  <input
                    type="checkbox"
                    checked={removed.includes(field.name)}
                    onChange={(event) =>
                      setRemoved(
                        event.target.checked
                          ? [...removed, field.name]
                          : removed.filter((name) => name !== field.name),
                      )
                    }
                  />
                  Remove this field
                </label>
              )}
            {mode === 'edit' && field.name === 'login_url' && (
              <p
                className={
                  urlMovedWithoutPassword
                    ? 'text-xs text-amber-700 dark:text-amber-400'
                    : 'text-xs text-slate-500'
                }
              >
                Changing the site needs the password again.
              </p>
            )}
          </div>
        ))}
        {hasExpiry && (
          <div className="flex flex-col gap-1.5">
            <label htmlFor={`${id}-expiry`} className="text-xs text-slate-400">
              Expires
            </label>
            <input
              id={`${id}-expiry`}
              type="datetime-local"
              value={expiry}
              onChange={(event) => setExpiry(event.target.value)}
              className={inputClass}
            />
            <p className="text-xs text-slate-500">
              {mode === 'edit'
                ? 'Empty means no expiry.'
                : 'Empty means no expiry. A saved future expiry is kept.'}
            </p>
          </div>
        )}
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-red-700 dark:text-red-400">
          {error}
        </p>
      )}
      <div className="mt-4 flex gap-2">
        <button
          type="submit"
          disabled={isPending || incomplete || urlMovedWithoutPassword}
          className="inline-flex h-10 items-center justify-center rounded-md bg-slate-100 px-4 text-sm font-medium text-slate-900 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isPending
            ? 'Saving...'
            : mode === 'add'
              ? 'Add login'
              : mode === 'edit'
                ? 'Save changes'
                : 'Replace login'}
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="inline-flex h-10 items-center justify-center rounded-md border border-slate-700 px-4 text-sm text-slate-300 transition-colors hover:bg-slate-800"
        >
          Cancel
        </button>
      </div>
    </form>
  )
}
