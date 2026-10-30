'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  CalendarClock,
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ListChecks,
  Play,
  Plus,
  RefreshCw,
  Settings2,
} from 'lucide-react'
import { type FormEvent, useEffect, useMemo, useState } from 'react'
import {
  type AutomationDefinition,
  type AutomationPolicy,
  type AutomationProfile,
  type AutomationProfileInput,
  type AutomationRun,
  type Config,
  type ConfigSchema,
  createAutomationProfile,
  fetchAutomationPolicy,
  fetchAutomationProfiles,
  fetchAutomationRegistry,
  fetchAutomationRuns,
  reviewAutomationProfile,
  runAutomationProfile,
  updateAutomationPolicy,
  updateAutomationProfile,
} from '@/lib/api/automations'
import { fetchProjectCatalog } from '@/lib/api/project-permissions'
import { cn } from '@/lib/utils'
import { ConfigFields } from './ConfigFields'

type Tab = 'profiles' | 'policy' | 'runs' | 'catalog'
const PAGE_SIZE = 50
const tabs: Array<{ id: Tab; label: string }> = [
  { id: 'profiles', label: 'Profiles' },
  { id: 'policy', label: 'Project policy' },
  { id: 'runs', label: 'Run history' },
  { id: 'catalog', label: 'Catalog' },
]

function timestamp(value: string | null | undefined): string {
  if (!value) return 'None'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : 'Request failed'
}

function scheduleText(profile: AutomationProfile): string {
  if (profile.schedule_type === 'every')
    return `Every ${Number(profile.schedule_value) / 60000} minutes`
  if (profile.schedule_type === 'at')
    return `Once at ${timestamp(profile.schedule_value)}`
  const cron = `${profile.schedule_value} (${profile.schedule_timezone})`
  const local =
    profile.schedule_timezone === 'UTC'
      ? utcCronLocalText(profile.schedule_value)
      : null
  return local ? `${local} · ${cron}` : cron
}

const WEEKDAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat']

// Common UTC cron shapes in the viewer's local time; null leaves the raw cron alone.
function utcCronLocalText(cron: string): string | null {
  const [minute, hour, dayOfMonth, month, weekday, ...rest] = cron
    .trim()
    .split(/\s+/)
  if (rest.length || dayOfMonth !== '*' || month !== '*') return null
  const every = /^\*\/(\d+)$/.exec(minute)
  if (every && hour === '*' && weekday === '*')
    return `Every ${every[1]} minutes`
  if (!/^\d+$/.test(minute)) return null
  if (hour === '*' && weekday === '*')
    return `Hourly at :${minute.padStart(2, '0')}`
  if (!/^\d+$/.test(hour) || !/^(\*|[0-6])$/.test(weekday)) return null
  // Any date works for the time; the weekday needs a date that falls on it in UTC.
  const at = new Date(Date.UTC(2026, 0, 4, Number(hour), Number(minute)))
  if (weekday !== '*') at.setUTCDate(at.getUTCDate() + Number(weekday))
  const time = at.toLocaleTimeString(undefined, {
    hour: 'numeric',
    minute: '2-digit',
  })
  return weekday === '*'
    ? `Daily at ${time} your time`
    : `${WEEKDAYS[at.getDay()]} at ${time} your time`
}

function localDateTime(value: string): string {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16)
}

function badge(tone: 'good' | 'warn' | 'muted' | 'bad'): string {
  return cn(
    'inline-flex items-center rounded-full border px-2.5 py-0.5 text-xs font-medium',
    tone === 'good' &&
      'border-emerald-700/50 bg-emerald-950/30 text-emerald-300',
    tone === 'warn' && 'border-amber-700/50 bg-amber-950/30 text-amber-300',
    tone === 'muted' && 'border-slate-700 bg-slate-800/70 text-slate-300',
    tone === 'bad' && 'border-rose-700/50 bg-rose-950/30 text-rose-300',
  )
}

function profileStatus(profile: AutomationProfile): {
  label: string
  tone: 'good' | 'warn' | 'muted'
} {
  if (profile.clock_owner === 'legacy')
    return { label: 'Legacy clock', tone: 'warn' }
  if (profile.effective_enabled) return { label: 'Active', tone: 'good' }
  return profile.enabled
    ? { label: 'Blocked', tone: 'warn' }
    : { label: 'Paused', tone: 'muted' }
}

// A paused or blocked profile keeps its last computed next_run_at, which goes stale.
function nextRunText(profile: AutomationProfile): string {
  if (profile.effective_enabled || profile.clock_owner === 'legacy')
    return timestamp(profile.next_run_at)
  return `Not scheduled (${profileStatus(profile).label.toLowerCase()})`
}

function ProfileForm({
  profile,
  definitions,
  projectId,
  busy,
  onSave,
  onCancel,
}: {
  profile: AutomationProfile | null
  definitions: AutomationDefinition[]
  projectId: string
  busy: boolean
  onSave: (input: AutomationProfileInput) => Promise<void>
  onCancel: () => void
}) {
  const availableDefinitions = definitions.filter(
    (item) =>
      item.owner_project_id === projectId ||
      item.owner_project_id === 'summitflow',
  )
  const [workflowKey, setWorkflowKey] = useState(
    profile?.workflow_key ?? availableDefinitions[0]?.workflow_key ?? '',
  )
  const initialDefinition = availableDefinitions.find(
    (item) => item.workflow_key === workflowKey,
  )
  const [label, setLabel] = useState(profile?.label ?? '')
  const [subjectId, setSubjectId] = useState(profile?.subject_id ?? '')
  const [scheduleType, setScheduleType] = useState<
    AutomationProfileInput['schedule_type']
  >(
    profile?.schedule_type ??
      initialDefinition?.default_schedule?.type ??
      'cron',
  )
  const [scheduleValue, setScheduleValue] = useState(
    profile?.schedule_type === 'at'
      ? localDateTime(profile.schedule_value)
      : (profile?.schedule_value ??
          initialDefinition?.default_schedule?.value ??
          ''),
  )
  const [timezone, setTimezone] = useState(
    profile?.schedule_timezone ??
      Intl.DateTimeFormat().resolvedOptions().timeZone ??
      initialDefinition?.default_schedule?.timezone ??
      'UTC',
  )
  const [enabled, setEnabled] = useState(profile?.enabled ?? false)
  const [config, setConfig] = useState<Config>(profile?.config ?? {})
  const definition = definitions.find(
    (item) => item.workflow_key === workflowKey,
  )

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!workflowKey || !projectId || !label.trim() || !scheduleValue.trim())
      return
    if (
      scheduleType === 'every' &&
      (!Number.isInteger(Number(scheduleValue)) ||
        Number(scheduleValue) < 60000)
    )
      return
    try {
      const submittedConfig: Config = { ...config }
      for (const [key, field] of Object.entries(
        definition?.config_schema?.properties ?? {},
      )) {
        if (!(key in submittedConfig) && field.default !== undefined)
          submittedConfig[key] = field.default
      }
      await onSave({
        project_id: projectId,
        subject_id: subjectId.trim() || null,
        workflow_key: workflowKey,
        label: label.trim(),
        schedule_type: scheduleType,
        schedule_value:
          scheduleType === 'at'
            ? new Date(scheduleValue).toISOString()
            : scheduleValue.trim(),
        schedule_timezone: timezone.trim() || 'UTC',
        config: submittedConfig,
        enabled,
      })
    } catch {
      // The parent surfaces the API error next to the form.
    }
  }

  return (
    <form
      onSubmit={(event) => void submit(event)}
      className="space-y-5"
      aria-label={
        profile ? 'Edit automation profile' : 'Create automation profile'
      }
    >
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="section-heading">
            {profile ? 'Edit profile' : 'Create profile'}
          </h2>
          <p className="section-copy mt-1">
            {projectId} · {definition?.owner_project_id || 'Select a workflow'}
          </p>
        </div>
        <button type="button" onClick={onCancel} className="button-secondary">
          Cancel
        </button>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm font-medium text-slate-200 sm:col-span-2">
          Workflow
          <select
            className="control-select mt-1 w-full"
            value={workflowKey}
            onChange={(event) => {
              const next = availableDefinitions.find(
                (item) => item.workflow_key === event.target.value,
              )
              setWorkflowKey(event.target.value)
              setConfig({})
              if (next?.default_schedule?.type)
                setScheduleType(next.default_schedule.type)
              setScheduleValue(next?.default_schedule?.value ?? '')
              setTimezone(next?.default_schedule?.timezone ?? 'UTC')
              setEnabled(next?.default_enabled ?? true)
            }}
            disabled={Boolean(profile)}
            required
          >
            <option value="">Select workflow</option>
            {availableDefinitions.map((item) => (
              <option key={item.workflow_key} value={item.workflow_key}>
                {item.label}
              </option>
            ))}
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-200">
          Profile name
          <input
            className="control-input mt-1"
            value={label}
            onChange={(event) => setLabel(event.target.value)}
            required
          />
        </label>
        <label className="block text-sm font-medium text-slate-200">
          Subject ID{' '}
          <span className="text-xs font-normal text-slate-500">(optional)</span>
          <input
            className="control-input mt-1"
            value={subjectId}
            onChange={(event) => setSubjectId(event.target.value)}
          />
        </label>
        <label className="block text-sm font-medium text-slate-200">
          Schedule
          <select
            className="control-select mt-1 w-full"
            value={scheduleType}
            onChange={(event) => {
              setScheduleType(
                event.target.value as AutomationProfileInput['schedule_type'],
              )
              setScheduleValue('')
            }}
          >
            <option value="cron">Cron</option>
            <option value="every">Interval</option>
            <option value="at">Once</option>
          </select>
        </label>
        <label className="block text-sm font-medium text-slate-200">
          {scheduleType === 'cron'
            ? 'Cron expression'
            : scheduleType === 'every'
              ? 'Interval (minutes)'
              : 'Run at'}
          <input
            className="control-input mt-1"
            type={
              scheduleType === 'at'
                ? 'datetime-local'
                : scheduleType === 'every'
                  ? 'number'
                  : 'text'
            }
            min={scheduleType === 'every' ? 1 : undefined}
            step={scheduleType === 'every' ? 1 : undefined}
            value={
              scheduleType === 'every' && scheduleValue
                ? String(Number(scheduleValue) / 60000)
                : scheduleValue
            }
            onChange={(event) =>
              setScheduleValue(
                scheduleType === 'every' && event.target.value
                  ? String(Number(event.target.value) * 60000)
                  : event.target.value,
              )
            }
            placeholder={
              scheduleType === 'cron'
                ? '0 9 * * *'
                : scheduleType === 'every'
                  ? '60'
                  : undefined
            }
            required
          />
        </label>
        <label className="block text-sm font-medium text-slate-200 sm:col-span-2">
          Timezone
          <input
            className="control-input mt-1"
            value={timezone}
            onChange={(event) => setTimezone(event.target.value)}
            required
          />
        </label>
      </div>
      <div className="border-t border-slate-800 pt-5">
        <h3 className="mb-3 text-sm font-semibold text-slate-100">
          Workflow settings
        </h3>
        <ConfigFields
          schema={definition?.config_schema}
          value={config}
          onChange={setConfig}
          idPrefix="profile-config"
        />
      </div>
      <label className="flex items-center gap-3 text-sm font-medium text-slate-200">
        <input
          type="checkbox"
          className="h-4 w-4 accent-amber-500"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enabled
      </label>
      <button
        type="submit"
        disabled={busy || !projectId || !workflowKey}
        className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
      >
        {busy ? 'Saving…' : profile ? 'Save profile' : 'Create profile'}
      </button>
    </form>
  )
}

function PolicyEditor({
  policy,
  schema,
  saving,
  onSave,
}: {
  policy: AutomationPolicy
  schema: AutomationDefinition['policy_schema']
  saving: boolean
  onSave: (enabled: boolean, config: Config) => Promise<void>
}) {
  const [enabled, setEnabled] = useState(policy.enabled)
  const [config, setConfig] = useState<Config>(policy.config)
  const changed =
    enabled !== policy.enabled ||
    JSON.stringify(config) !== JSON.stringify(policy.config)
  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        void onSave(enabled, config).catch(() => {})
      }}
      className="section-card space-y-5"
    >
      <div>
        <h2 className="section-heading">{policy.project_id} policy</h2>
        <p className="section-copy mt-1">
          This project gate applies to its registered automation profiles.
        </p>
        {policy.sync_pending && (
          <p role="status" className="mt-3 text-sm text-amber-300">
            Jobinator is still applying the updated limits. New automated runs
            will wait.
          </p>
        )}
      </div>
      <label className="flex items-center gap-3 text-sm font-medium text-slate-200">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
          className="h-4 w-4 accent-amber-500"
        />
        Allow automations for this project
      </label>
      <ConfigFields
        schema={schema}
        value={config}
        onChange={setConfig}
        idPrefix="project-policy"
      />
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-4">
        <p className="text-xs text-slate-500">
          Updated {timestamp(policy.updated_at)} · revision {policy.revision}
        </p>
        <button
          type="submit"
          disabled={!changed || saving}
          className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          {saving ? 'Saving…' : 'Save policy'}
        </button>
      </div>
    </form>
  )
}

/** `label` is the run's profile name when that profile is loaded; else the workflow key stands in. */
function RunRow({ run, label }: { run: AutomationRun; label?: string }) {
  return (
    <details className="border-b border-slate-800/80 px-4 py-3 last:border-b-0">
      <summary className="flex cursor-pointer list-none flex-wrap items-center justify-between gap-3 focus-visible:outline-2 focus-visible:outline-amber-500">
        <span className="flex min-w-0 flex-wrap items-center gap-2">
          <span
            className={badge(
              run.status === 'completed' || run.status === 'succeeded'
                ? 'good'
                : run.status === 'failed'
                  ? 'bad'
                  : 'warn',
            )}
          >
            {run.status}
          </span>
          <span className="truncate text-sm font-medium text-slate-200">
            {label ?? run.workflow_key}
          </span>
          <span className="text-xs text-slate-500">
            {run.trigger || 'scheduled'}
          </span>
        </span>
        <time className="text-xs text-slate-400">
          {timestamp(run.created_at)}
        </time>
      </summary>
      <dl className="mt-4 grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Workflow</dt>
          <dd className="mt-1 break-all text-slate-300">{run.workflow_key}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Run ID</dt>
          <dd className="mt-1 break-all text-slate-300">{run.id}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Profile ID</dt>
          <dd className="mt-1 break-all text-slate-300">{run.profile_id}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Accepted</dt>
          <dd className="mt-1 text-slate-300">{timestamp(run.accepted_at)}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Completed</dt>
          <dd className="mt-1 text-slate-300">{timestamp(run.completed_at)}</dd>
        </div>
      </dl>
      <dl className="mt-3 grid gap-3 text-xs sm:grid-cols-2">
        <div>
          <dt className="text-slate-500">Scheduled for</dt>
          <dd className="mt-1 text-slate-300">
            {timestamp(run.scheduled_for)}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Owner run ID</dt>
          <dd className="mt-1 break-all text-slate-300">
            {run.owner_run_id || 'None'}
          </dd>
        </div>
        <div>
          <dt className="text-slate-500">Definition version</dt>
          <dd className="mt-1 text-slate-300">{run.definition_version}</dd>
        </div>
        <div>
          <dt className="text-slate-500">Profile revision</dt>
          <dd className="mt-1 text-slate-300">{run.profile_revision}</dd>
        </div>
        <div className="sm:col-span-2">
          <dt className="text-slate-500">Occurrence key</dt>
          <dd className="mt-1 break-all text-slate-300">
            {run.occurrence_key}
          </dd>
        </div>
      </dl>
      {run.gate_reasons.length > 0 && (
        <p className="mt-3 text-xs text-amber-300">
          Gate reasons:{' '}
          {run.gate_reasons
            .map((reason) => reason.replaceAll('_', ' '))
            .join(', ')}
        </p>
      )}
      {run.error && (
        <p className="mt-3 rounded-lg border border-rose-800/50 bg-rose-950/20 p-3 text-sm text-rose-300">
          {run.error}
        </p>
      )}
      {run.owner_receipt && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-slate-400">Owner receipt</p>
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-all rounded-lg bg-slate-950/70 p-3 text-xs text-slate-300">
            {JSON.stringify(run.owner_receipt, null, 2)}
          </pre>
        </div>
      )}
    </details>
  )
}

export default function AutomationsPage() {
  const queryClient = useQueryClient()
  const [projectId, setProjectId] = useState('')
  const [tab, setTab] = useState<Tab>('profiles')
  const [profileOffset, setProfileOffset] = useState(0)
  const [runOffset, setRunOffset] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [editing, setEditing] = useState(false)
  const [creating, setCreating] = useState(false)
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)

  useEffect(() => {
    const requestedProject = new URLSearchParams(window.location.search).get(
      'project_id',
    )
    if (requestedProject) setProjectId(requestedProject)
  }, [])

  const catalogQuery = useQuery({
    queryKey: ['projects-catalog'],
    queryFn: fetchProjectCatalog,
  })
  const registryQuery = useQuery({
    queryKey: ['automation-registry'],
    queryFn: fetchAutomationRegistry,
  })
  const profilesQuery = useQuery({
    queryKey: ['automation-profiles', projectId, profileOffset],
    queryFn: () =>
      fetchAutomationProfiles(projectId || undefined, PAGE_SIZE, profileOffset),
    refetchInterval: 30000,
  })
  const runsQuery = useQuery({
    queryKey: ['automation-runs', projectId, selectedId, runOffset],
    queryFn: () =>
      fetchAutomationRuns({
        projectId: projectId || undefined,
        profileId: selectedId || undefined,
        limit: PAGE_SIZE,
        offset: runOffset,
      }),
    enabled: tab === 'runs',
    refetchInterval: tab === 'runs' ? 15000 : false,
  })
  const policyQuery = useQuery({
    queryKey: ['automation-policy', projectId],
    queryFn: () => fetchAutomationPolicy(projectId),
    enabled: Boolean(projectId) && tab === 'policy',
  })

  useEffect(() => {
    setProfileOffset(0)
    setRunOffset(0)
    setSelectedId(null)
    setEditing(false)
    setCreating(false)
  }, [projectId])
  useEffect(() => {
    if (!creating) return
    const form = document.getElementById('new-automation-profile')
    if (!form) return
    const headerBottom =
      document.querySelector('.page-header')?.getBoundingClientRect().bottom ??
      0
    form.style.scrollMarginTop = `${headerBottom + 16}px`
    form.scrollIntoView({ block: 'start' })
  }, [creating])
  const profiles = profilesQuery.data?.items ?? []
  const displayProfiles = [...profiles].sort((a, b) =>
    `${a.project_id}:${a.subject_id ?? ''}:${a.label}`.localeCompare(
      `${b.project_id}:${b.subject_id ?? ''}:${b.label}`,
    ),
  )
  const selected = profiles.find((item) => item.id === selectedId) ?? null
  const definitions = Array.from(
    new Map(
      (registryQuery.data?.definitions ?? [])
        .slice()
        .sort((a, b) => a.version - b.version)
        .map((item) => [item.workflow_key, item]),
    ).values(),
  )
  const selectedDefinition = definitions.find(
    (item) => item.workflow_key === selected?.workflow_key,
  )
  const policySchema = useMemo<ConfigSchema | undefined>(() => {
    if (!projectId) return undefined
    const applicable = definitions.filter(
      (item) =>
        item.owner_project_id === projectId ||
        (item.owner_project_id === 'summitflow' &&
          (projectId === 'summitflow' ||
            profiles.some(
              (profile) => profile.workflow_key === item.workflow_key,
            ))),
    )
    const base = applicable[0]?.policy_schema
    if (!base) return undefined
    return {
      ...base,
      properties: Object.assign(
        {},
        ...applicable.map((item) => item.policy_schema?.properties ?? {}),
      ),
    }
  }, [definitions, profiles, projectId])
  const projectOptions = useMemo(() => {
    const entries = new Map<string, string>()
    for (const item of catalogQuery.data ?? [])
      entries.set(item.project_id, item.label || item.project_id)
    for (const item of profiles)
      if (!entries.has(item.project_id))
        entries.set(item.project_id, item.project_id)
    return [...entries].sort(([a], [b]) => a.localeCompare(b))
  }, [catalogQuery.data, profiles])

  const refresh = () => {
    void Promise.all([
      queryClient.invalidateQueries({ queryKey: ['automation-registry'] }),
      queryClient.invalidateQueries({ queryKey: ['automation-profiles'] }),
      queryClient.invalidateQueries({ queryKey: ['automation-runs'] }),
      queryClient.invalidateQueries({ queryKey: ['automation-policy'] }),
    ])
  }
  const notify = (message: string) => {
    setActionError(null)
    setActionSuccess(message)
    refresh()
  }
  const fail = (error: unknown) => {
    setActionSuccess(null)
    setActionError(errorText(error))
  }
  const saveMutation = useMutation({
    mutationFn: (input: AutomationProfileInput) =>
      selected && editing
        ? updateAutomationProfile(selected.id, {
            subject_id: input.subject_id,
            label: input.label,
            schedule_type: input.schedule_type,
            schedule_value: input.schedule_value,
            schedule_timezone: input.schedule_timezone,
            config: input.config,
            enabled: input.enabled,
            expected_revision: selected.revision,
          })
        : createAutomationProfile(input),
    onSuccess: (result) => {
      setCreating(false)
      setEditing(false)
      setSelectedId(result.id)
      notify('Profile saved')
    },
    onError: fail,
  })
  const policyMutation = useMutation({
    mutationFn: ({ enabled, config }: { enabled: boolean; config: Config }) =>
      updateAutomationPolicy(projectId, {
        enabled,
        config,
        expected_revision: policyQuery.data?.revision ?? 0,
      }),
    onSuccess: () => notify('Project policy saved'),
    onError: fail,
  })
  const runMutation = useMutation({
    mutationFn: runAutomationProfile,
    onSuccess: (run) => {
      setTab('runs')
      if (run.status === 'rejected') {
        fail(
          new Error(
            `Run blocked: ${run.gate_reasons.map((reason) => reason.replaceAll('_', ' ')).join(', ') || 'admission rejected'}`,
          ),
        )
        refresh()
      } else {
        notify('Run admitted')
      }
    },
    onError: fail,
  })
  const reviewMutation = useMutation({
    mutationFn: reviewAutomationProfile,
    onSuccess: () => notify('Runs marked reviewed'),
    onError: fail,
  })
  const toggleMutation = useMutation({
    mutationFn: (profile: AutomationProfile) =>
      updateAutomationProfile(profile.id, {
        enabled: !profile.enabled,
        expected_revision: profile.revision,
      }),
    onSuccess: () => notify('Profile updated'),
    onError: fail,
  })

  const pageTotal =
    tab === 'runs'
      ? (runsQuery.data?.total ?? 0)
      : (profilesQuery.data?.total ?? 0)
  const pageOffset = tab === 'runs' ? runOffset : profileOffset
  const changePage = (next: number) => {
    if (tab === 'runs') {
      setRunOffset(next)
      return
    }
    setProfileOffset(next)
    setSelectedId(null)
    setEditing(false)
  }
  const setActiveTab = (next: Tab) => {
    setTab(next)
    setRunOffset(0)
    setActionError(null)
    setActionSuccess(null)
  }

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-60" />
      <header className="page-header">
        <div className="page-container page-header-row px-4 lg:px-8">
          <div className="page-title-group">
            <div className="page-title-icon">
              <CalendarClock className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <h1 className="page-title">Automations</h1>
              <p className="page-subtitle">
                Registered schedules, project policy, and runs
              </p>
            </div>
          </div>
          <div className="page-toolbar">
            <button
              type="button"
              onClick={refresh}
              className="button-secondary"
              aria-label="Refresh automations"
            >
              <RefreshCw className="h-4 w-4" />
              Refresh
            </button>
            <button
              type="button"
              onClick={() => {
                setTab('profiles')
                setCreating(true)
                setEditing(false)
                setSelectedId(null)
              }}
              disabled={
                !projectId ||
                !definitions.some(
                  (item) =>
                    item.owner_project_id === projectId ||
                    item.owner_project_id === 'summitflow',
                )
              }
              className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Plus className="h-4 w-4" />
              New profile
            </button>
          </div>
        </div>
      </header>
      <main className="page-container page-frame space-y-5">
        <div className="control-strip">
          <label className="flex min-w-0 flex-1 flex-col gap-1 text-xs font-medium text-slate-400 sm:max-w-sm">
            Project
            <select
              className="control-select w-full"
              value={projectId}
              onChange={(event) => setProjectId(event.target.value)}
            >
              <option value="">All projects</option>
              {projectOptions.map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <p className="text-xs text-slate-400">
            {profilesQuery.data
              ? `${profilesQuery.data.total} profiles`
              : 'Loading profiles…'}
          </p>
        </div>
        <nav
          aria-label="Automation sections"
          className="flex gap-1 overflow-x-auto border-b border-slate-800 pb-1"
        >
          {tabs.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => setActiveTab(item.id)}
              aria-pressed={tab === item.id}
              className={cn(
                'shrink-0 rounded-t-lg px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-amber-500',
                tab === item.id
                  ? 'border-b-2 border-amber-400 text-slate-100'
                  : 'text-slate-400 hover:text-slate-200',
              )}
            >
              {item.label}
            </button>
          ))}
        </nav>
        {actionError && (
          <div
            role="alert"
            className="rounded-xl border border-rose-800/60 bg-rose-950/25 px-4 py-3 text-sm text-rose-300"
          >
            {actionError}
          </div>
        )}
        {actionSuccess && (
          <div
            role="status"
            className="rounded-xl border border-emerald-800/60 bg-emerald-950/25 px-4 py-3 text-sm text-emerald-300"
          >
            {actionSuccess}
          </div>
        )}
        {registryQuery.error && (
          <div role="alert" className="section-card text-sm text-rose-300">
            {errorText(registryQuery.error)}
          </div>
        )}
        {tab === 'profiles' && (
          <div className="space-y-4">
            {creating && (
              <section
                id="new-automation-profile"
                className="section-card"
                aria-label="New automation profile"
              >
                <div className="max-w-4xl">
                  <ProfileForm
                    key="new"
                    profile={null}
                    definitions={definitions}
                    projectId={projectId}
                    busy={saveMutation.isPending}
                    onSave={async (input) => {
                      await saveMutation.mutateAsync(input)
                    }}
                    onCancel={() => setCreating(false)}
                  />
                </div>
              </section>
            )}
            <section
              className="panel-surface min-w-0 overflow-hidden"
              aria-label="Automation profiles"
            >
              <div className="border-b border-slate-800 px-4 py-3">
                <h2 className="section-heading">Profiles</h2>
              </div>
              {profilesQuery.isLoading ? (
                <p className="p-5 text-sm text-slate-400">Loading profiles…</p>
              ) : profilesQuery.error ? (
                <div className="p-5 text-sm text-rose-300" role="alert">
                  {errorText(profilesQuery.error)}{' '}
                  <button
                    type="button"
                    onClick={() => void profilesQuery.refetch()}
                    className="underline"
                  >
                    Retry
                  </button>
                </div>
              ) : profiles.length === 0 ? (
                <p className="p-5 text-sm text-slate-400">
                  No profiles registered for this selection.
                </p>
              ) : (
                <div className="divide-y divide-slate-800/80">
                  {displayProfiles.map((profile, index) => {
                    const expanded = selectedId === profile.id
                    return (
                      <div key={profile.id}>
                        {(index === 0 ||
                          displayProfiles[index - 1].project_id !==
                            profile.project_id ||
                          displayProfiles[index - 1].subject_id !==
                            profile.subject_id) && (
                          <h3 className="border-b border-slate-800/80 bg-slate-950/50 px-4 py-2 text-xs font-semibold text-slate-400">
                            {profile.project_id}
                            {profile.subject_id
                              ? ` / ${profile.subject_id}`
                              : ' / project-wide'}
                          </h3>
                        )}
                        <button
                          type="button"
                          onClick={() => {
                            setSelectedId(expanded ? null : profile.id)
                            setEditing(false)
                            setCreating(false)
                            setActionError(null)
                          }}
                          aria-expanded={expanded}
                          aria-controls={
                            expanded
                              ? `profile-details-${profile.id}`
                              : undefined
                          }
                          className={cn(
                            'w-full px-4 py-3 text-left transition hover:bg-slate-800/50 focus-visible:outline-2 focus-visible:outline-amber-500 sm:px-5',
                            expanded && 'bg-amber-950/20',
                          )}
                        >
                          <span className="flex min-w-0 items-start justify-between gap-3">
                            <span className="min-w-0">
                              <span className="block break-words text-sm font-semibold text-slate-100">
                                {profile.label}
                              </span>
                              <span className="mt-1 block break-all text-xs text-slate-400">
                                {profile.workflow_key}
                              </span>
                              <span className="mt-1 block text-xs text-slate-500">
                                {scheduleText(profile)}
                              </span>
                              {profile.unreviewed_count > 0 && (
                                <span className="mt-2 block text-xs font-medium text-amber-300">
                                  {profile.unreviewed_count} runs since last
                                  marked reviewed
                                </span>
                              )}
                            </span>
                            <span className="flex shrink-0 items-center gap-2">
                              <span
                                className={badge(profileStatus(profile).tone)}
                              >
                                {profileStatus(profile).label}
                              </span>
                              <ChevronDown
                                aria-hidden="true"
                                className={cn(
                                  'h-4 w-4 text-slate-400 transition-transform',
                                  expanded && 'rotate-180',
                                )}
                              />
                            </span>
                          </span>
                        </button>
                        {expanded && selected && (
                          <section
                            id={`profile-details-${profile.id}`}
                            aria-label={`${profile.label} details`}
                            className="border-t border-amber-900/40 bg-slate-950/40 px-4 py-5 sm:px-6"
                          >
                            <div className="max-w-4xl">
                              {editing ? (
                                <ProfileForm
                                  key={selected.id}
                                  profile={selected}
                                  definitions={definitions}
                                  projectId={selected.project_id}
                                  busy={saveMutation.isPending}
                                  onSave={async (input) => {
                                    await saveMutation.mutateAsync(input)
                                  }}
                                  onCancel={() => setEditing(false)}
                                />
                              ) : (
                                <div className="space-y-5">
                                  {selectedDefinition?.description && (
                                    <p className="text-sm leading-6 text-slate-300">
                                      {selectedDefinition.description}
                                    </p>
                                  )}
                                  {selected.gate_reasons.length > 0 && (
                                    <div className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-3">
                                      <p className="text-xs font-semibold text-amber-300">
                                        Schedule gates
                                      </p>
                                      <ul className="mt-1 list-inside list-disc text-sm text-amber-200">
                                        {selected.gate_reasons.map((reason) => (
                                          <li key={reason}>
                                            {reason.replaceAll('_', ' ')}
                                          </li>
                                        ))}
                                      </ul>
                                    </div>
                                  )}
                                  {selected.clock_owner === 'legacy' && (
                                    <p className="rounded-xl border border-amber-800/50 bg-amber-950/20 p-3 text-sm text-amber-200">
                                      This schedule still runs under its
                                      original owner. Changes to its profile
                                      here do not change that live clock.
                                    </p>
                                  )}
                                  <dl className="grid gap-3 text-sm sm:grid-cols-2">
                                    <div>
                                      <dt className="text-xs text-slate-500">
                                        Schedule
                                      </dt>
                                      <dd className="mt-1 text-slate-200">
                                        {scheduleText(selected)}
                                      </dd>
                                    </div>
                                    <div>
                                      <dt className="text-xs text-slate-500">
                                        Next run
                                      </dt>
                                      <dd className="mt-1 text-slate-200">
                                        {nextRunText(selected)}
                                      </dd>
                                    </div>
                                    <div>
                                      <dt className="text-xs text-slate-500">
                                        Last run
                                      </dt>
                                      <dd className="mt-1 text-slate-200">
                                        {timestamp(selected.last_run_at)}
                                      </dd>
                                    </div>
                                    <div>
                                      <dt className="text-xs text-slate-500">
                                        Revision
                                      </dt>
                                      <dd className="mt-1 text-slate-200">
                                        {selected.revision}
                                      </dd>
                                    </div>
                                  </dl>
                                  <div className="flex flex-wrap gap-2 border-t border-slate-800 pt-4">
                                    <button
                                      type="button"
                                      onClick={() => setEditing(true)}
                                      disabled={
                                        selected.clock_owner === 'legacy'
                                      }
                                      className="button-secondary disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                      <Settings2 className="h-4 w-4" />
                                      Edit
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        toggleMutation.mutate(selected)
                                      }
                                      disabled={
                                        toggleMutation.isPending ||
                                        selected.clock_owner === 'legacy'
                                      }
                                      className="button-secondary disabled:opacity-50"
                                    >
                                      {selected.enabled ? 'Pause' : 'Enable'}
                                    </button>
                                    <button
                                      type="button"
                                      onClick={() =>
                                        runMutation.mutate(selected.id)
                                      }
                                      disabled={
                                        runMutation.isPending ||
                                        (!selected.enabled &&
                                          !selectedDefinition?.manual_when_disabled)
                                      }
                                      className="button-primary disabled:cursor-not-allowed disabled:opacity-50"
                                    >
                                      <Play className="h-4 w-4" />
                                      Run now
                                    </button>
                                    {selected.unreviewed_count > 0 && (
                                      <button
                                        type="button"
                                        onClick={() =>
                                          reviewMutation.mutate(selected.id)
                                        }
                                        disabled={reviewMutation.isPending}
                                        className="button-secondary disabled:opacity-50"
                                      >
                                        <ListChecks className="h-4 w-4" />
                                        Mark reviewed
                                      </button>
                                    )}
                                  </div>
                                  {!selected.enabled &&
                                  !selectedDefinition?.manual_when_disabled ? (
                                    <p className="text-xs text-slate-500">
                                      Manual runs are unavailable for this
                                      workflow.
                                    </p>
                                  ) : null}
                                  <button
                                    type="button"
                                    onClick={() => setActiveTab('runs')}
                                    className="text-sm text-amber-300 hover:underline"
                                  >
                                    View run history
                                  </button>
                                </div>
                              )}
                            </div>
                          </section>
                        )}
                      </div>
                    )
                  })}
                </div>
              )}
            </section>
          </div>
        )}
        {tab === 'policy' &&
          (!projectId ? (
            <div className="empty-surface">
              <p className="text-sm text-slate-400">
                Select a project to inspect its automation policy.
              </p>
            </div>
          ) : policyQuery.isLoading ? (
            <div className="section-card text-sm text-slate-400">
              Loading project policy…
            </div>
          ) : policyQuery.error ? (
            <div className="section-card text-sm text-rose-300" role="alert">
              {errorText(policyQuery.error)}{' '}
              <button
                type="button"
                onClick={() => void policyQuery.refetch()}
                className="underline"
              >
                Retry
              </button>
            </div>
          ) : policyQuery.data ? (
            <div className="space-y-5">
              <PolicyEditor
                key={`${projectId}-${policyQuery.data.revision}`}
                policy={policyQuery.data}
                schema={policySchema}
                saving={policyMutation.isPending}
                onSave={async (enabled, config) => {
                  await policyMutation.mutateAsync({ enabled, config })
                }}
              />
            </div>
          ) : (
            <div className="empty-surface">
              No policy found for this project.
            </div>
          ))}
        {tab === 'runs' && (
          <section className="panel-surface overflow-hidden">
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 p-4">
              <div>
                <h2 className="section-heading">Run history</h2>
                <p className="mt-1 text-xs text-slate-400">
                  {selected ? selected.label : projectId || 'All projects'}
                </p>
              </div>
              <label className="text-xs text-slate-400">
                Profile
                <select
                  className="control-select ml-2 max-w-[16rem]"
                  value={selectedId ?? ''}
                  onChange={(event) => {
                    setSelectedId(event.target.value || null)
                    setRunOffset(0)
                  }}
                >
                  <option value="">All profiles</option>
                  {profiles.map((profile) => (
                    <option key={profile.id} value={profile.id}>
                      {profile.label}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            {runsQuery.isLoading ? (
              <p className="p-5 text-sm text-slate-400">Loading runs…</p>
            ) : runsQuery.error ? (
              <div role="alert" className="p-5 text-sm text-rose-300">
                {errorText(runsQuery.error)}{' '}
                <button
                  type="button"
                  onClick={() => void runsQuery.refetch()}
                  className="underline"
                >
                  Retry
                </button>
              </div>
            ) : runsQuery.data?.items.length ? (
              runsQuery.data.items.map((run) => (
                <RunRow
                  key={run.id}
                  run={run}
                  label={
                    profiles.find((profile) => profile.id === run.profile_id)
                      ?.label
                  }
                />
              ))
            ) : (
              <p className="p-5 text-sm text-slate-400">
                No runs for this selection.
              </p>
            )}
          </section>
        )}
        {tab === 'catalog' && (
          <section className="space-y-3">
            <div>
              <h2 className="section-heading">Registered workflows</h2>
              <p className="section-copy mt-1">
                Choose a workflow when creating a profile for a project or
                subject.
              </p>
            </div>
            {registryQuery.isLoading ? (
              <div className="section-card text-sm text-slate-400">
                Loading catalog…
              </div>
            ) : definitions.length === 0 ? (
              <div className="empty-surface text-sm text-slate-400">
                No workflows registered.
              </div>
            ) : (
              <div className="grid gap-3 md:grid-cols-2">
                {definitions.map((item) => (
                  <article key={item.workflow_key} className="section-card">
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <h3 className="text-sm font-semibold text-slate-100">
                        {item.label}
                      </h3>
                      <span className="page-pill">{item.owner_project_id}</span>
                    </div>
                    <p className="mt-2 text-xs text-slate-500">
                      {item.workflow_key} · version {item.version}
                    </p>
                    {item.description && (
                      <p className="mt-3 text-sm leading-6 text-slate-300">
                        {item.description}
                      </p>
                    )}
                    <dl className="mt-3 grid gap-2 border-t border-slate-800 pt-3 text-xs sm:grid-cols-2">
                      <div>
                        <dt className="text-slate-500">Default schedule</dt>
                        <dd className="mt-1 text-slate-300">
                          {item.default_schedule?.value || 'Not set'}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Overlap</dt>
                        <dd className="mt-1 text-slate-300">
                          {item.overlap_strategy?.replaceAll('_', ' ') ||
                            'Not set'}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Manual when paused</dt>
                        <dd className="mt-1 text-slate-300">
                          {item.manual_when_disabled ? 'Allowed' : 'Blocked'}
                        </dd>
                      </div>
                      <div>
                        <dt className="text-slate-500">Dispatch</dt>
                        <dd className="mt-1 text-slate-300">
                          {item.dispatch_kind}
                        </dd>
                      </div>
                    </dl>
                  </article>
                ))}
              </div>
            )}
          </section>
        )}
        {(tab === 'profiles' || tab === 'runs') && pageTotal > PAGE_SIZE && (
          <div className="flex items-center justify-between gap-3 text-xs text-slate-400">
            <span>
              {pageOffset + 1}–{Math.min(pageOffset + PAGE_SIZE, pageTotal)} of{' '}
              {pageTotal}
            </span>
            <div className="flex gap-2">
              <button
                type="button"
                aria-label="Previous page"
                disabled={pageOffset === 0}
                onClick={() => changePage(Math.max(0, pageOffset - PAGE_SIZE))}
                className="button-secondary disabled:opacity-50"
              >
                <ChevronLeft className="h-4 w-4" />
              </button>
              <button
                type="button"
                aria-label="Next page"
                disabled={pageOffset + PAGE_SIZE >= pageTotal}
                onClick={() => changePage(pageOffset + PAGE_SIZE)}
                className="button-secondary disabled:opacity-50"
              >
                <ChevronRight className="h-4 w-4" />
              </button>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
