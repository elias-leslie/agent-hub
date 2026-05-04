import { AlertCircle, CheckCircle2, Loader2, RotateCcw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { buildApiUrl, fetchApi } from '@/lib/api-config'
import { cn } from '@/lib/utils'
import type { Persona, PersonaUpdate } from '@/types/persona'

interface IdentityTabProps {
  persona: Persona
  onUpdate: (fields: PersonaUpdate) => void
  onPersonaRefresh?: (updated: Persona) => void
}

const PHASE_CONFIG = {
  complete: {
    color: 'bg-emerald-500',
    pulse: false,
    label: 'Onboarded',
    description: 'Persona has completed initial setup',
  },
  pending_approval: {
    color: 'bg-blue-500',
    pulse: true,
    label: 'Pending Approval',
    description: 'Onboarding submitted — awaiting dual-model review',
  },
  in_progress: {
    color: 'bg-amber-500',
    pulse: true,
    label: 'Onboarding In Progress',
    description: 'Structured questionnaire is underway',
  },
  not_started: {
    color: 'bg-amber-500',
    pulse: false,
    label: 'Awaiting First Interaction',
    description:
      'Bootstrap instructions will be injected on first conversation',
  },
} as const

const USER_PROFILE_FIELDS = [
  ['user_identity', 'User Identity', 'Name, preferred address, identity notes'],
  [
    'work_context',
    'Work Context',
    'Role, projects, goals, operating environment',
  ],
  [
    'communication_style',
    'Communication Style',
    'Tone, directness, verbosity, feedback style',
  ],
  [
    'autonomy_level',
    'Autonomy Level',
    'What this persona should decide alone vs escalate',
  ],
  [
    'notification_preferences',
    'Notification Preferences',
    'Push thresholds, quiet hours, urgency rules',
  ],
  ['timezone', 'Timezone', 'Canonical timezone, e.g. America/New_York'],
  [
    'working_schedule',
    'Working Schedule',
    'Hours, availability, focus windows',
  ],
  [
    'priorities_values',
    'Priorities and Values',
    'Speed vs quality, docs, testing, tradeoffs',
  ],
  [
    'tools_and_integrations',
    'Tools and Integrations',
    'Preferred services, workflows, constraints',
  ],
  [
    'boundaries_and_escalation',
    'Boundaries and Escalation',
    'No-go zones and mandatory escalations',
  ],
] as const

export function IdentityTab({
  persona,
  onUpdate,
  onPersonaRefresh,
}: IdentityTabProps) {
  const [nameValue, setNameValue] = useState(persona.name)
  const [greetingValue, setGreetingValue] = useState(persona.greeting || '')

  useEffect(() => {
    setNameValue(persona.name)
    setGreetingValue(persona.greeting || '')
  }, [persona.name, persona.greeting])

  const handleNameBlur = useCallback(() => {
    if (nameValue.trim() && nameValue !== persona.name) {
      onUpdate({ name: nameValue.trim() })
    }
  }, [nameValue, persona.name, onUpdate])

  const handleGreetingBlur = useCallback(() => {
    if (greetingValue !== (persona.greeting || '')) {
      onUpdate({ greeting: greetingValue })
    }
  }, [greetingValue, persona.greeting, onUpdate])

  const [resetting, setResetting] = useState(false)
  const [resetState, setResetState] = useState<{
    status: 'idle' | 'success' | 'error'
    message: string | null
  }>({ status: 'idle', message: null })

  const handleResetOnboarding = useCallback(async () => {
    setResetting(true)
    setResetState({ status: 'idle', message: null })
    try {
      const res = await fetchApi(buildApiUrl('/api/persona/reset-onboarding'), {
        method: 'POST',
      })
      if (!res.ok) {
        throw new Error(`Reset failed with status ${res.status}`)
      }
      const updated = await res.json()
      onPersonaRefresh?.(updated)
      setResetState({
        status: 'success',
        message:
          'Onboarding reset. Bootstrap instructions will be injected into the next new conversation.',
      })
    } catch (err) {
      setResetState({
        status: 'error',
        message:
          err instanceof Error ? err.message : 'Failed to reset onboarding',
      })
    } finally {
      setResetting(false)
    }
  }, [onPersonaRefresh])

  const phase =
    persona.onboarding_phase ||
    (persona.onboarding_complete ? 'complete' : 'not_started')
  const config = PHASE_CONFIG[phase] || PHASE_CONFIG.not_started
  const showReset = phase === 'complete' || phase === 'in_progress'

  return (
    <div className="space-y-6">
      <div>
        <p className="section-kicker">Persona Identity</p>
        <h2 className="section-heading mt-2">Identity</h2>
        <p className="section-copy mt-2">
          Core identity settings for your persona.
        </p>
      </div>

      <div className="space-y-5">
        {/* Display Name */}
        <section className="section-card space-y-5">
          <div className="grid gap-5 lg:grid-cols-[minmax(0,1.1fr)_minmax(0,0.9fr)]">
            <div className="space-y-5">
              <div>
                <label className="detail-label mb-2 block">Display Name</label>
                <input
                  type="text"
                  value={nameValue}
                  onChange={(e) => setNameValue(e.target.value)}
                  onBlur={handleNameBlur}
                  onKeyDown={(e) => e.key === 'Enter' && handleNameBlur()}
                  maxLength={100}
                  className="control-input max-w-xl"
                />
                <p className="mt-2 text-xs text-slate-400">
                  Injected into every conversation via the identity tag.
                </p>
              </div>

              <div>
                <label className="detail-label mb-2 block">Agent Slug</label>
                <div className="detail-card max-w-xl">
                  <p className="text-sm font-mono text-slate-300">
                    {persona.agent_slug}
                  </p>
                </div>
              </div>

              <div>
                <label className="detail-label mb-2 block">
                  Greeting Message
                </label>
                <textarea
                  value={greetingValue}
                  onChange={(e) => setGreetingValue(e.target.value)}
                  onBlur={handleGreetingBlur}
                  rows={4}
                  className="control-input min-h-32 max-w-xl resize-y"
                  placeholder="Custom greeting for new sessions..."
                />
              </div>
            </div>

            <div className="detail-card space-y-4">
              <div>
                <p className="detail-label">Onboarding Status</p>
                <p className="mt-2 text-sm font-medium text-slate-100">
                  {config.label}
                </p>
                <p className="mt-2 text-sm text-slate-400">
                  {config.description}
                </p>
              </div>
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    'h-2.5 w-2.5 rounded-full',
                    config.color,
                    config.pulse && 'animate-pulse',
                  )}
                />
                <span className="text-xs text-slate-400">
                  {persona.onboarding_attempts > 0
                    ? `${persona.onboarding_attempts} onboarding attempt${persona.onboarding_attempts !== 1 ? 's' : ''}`
                    : 'No onboarding attempts yet'}
                </span>
              </div>
              {showReset && (
                <button
                  onClick={handleResetOnboarding}
                  disabled={resetting}
                  className="button-secondary"
                  title="Re-run onboarding bootstrap on next conversation"
                >
                  {resetting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <RotateCcw className="h-4 w-4" />
                  )}
                  Reset Onboarding
                </button>
              )}
              {resetState.message && (
                <div
                  className={cn(
                    'rounded-2xl border px-4 py-3 text-sm',
                    resetState.status === 'success'
                      ? 'border-emerald-800/50 bg-emerald-950/30 text-emerald-300'
                      : 'border-rose-800/50 bg-rose-950/30 text-rose-300',
                  )}
                >
                  <div className="flex items-start gap-2">
                    {resetState.status === 'success' ? (
                      <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" />
                    ) : (
                      <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                    )}
                    <p>{resetState.message}</p>
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="space-y-4">
            <div>
              <h3 className="section-heading">User Profile</h3>
              <p className="section-copy mt-2">
                Structured user preferences this persona can rely on
                consistently at runtime.
              </p>
            </div>
            <div className="grid gap-4">
              {USER_PROFILE_FIELDS.map(([field, label, placeholder]) => (
                <label key={field} className="detail-card space-y-2">
                  <span className="block text-sm font-medium text-slate-200">
                    {label}
                  </span>
                  <textarea
                    value={persona.user_profile?.[field] ?? ''}
                    placeholder={placeholder}
                    onChange={(event) =>
                      onUpdate({
                        user_profile: {
                          ...(persona.user_profile ?? {}),
                          [field]: event.target.value,
                        },
                      })
                    }
                    rows={field === 'timezone' ? 2 : 3}
                    className="control-input min-h-24 resize-y"
                  />
                </label>
              ))}
            </div>
          </div>
        </section>
      </div>
    </div>
  )
}
