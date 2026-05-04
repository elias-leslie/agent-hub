import { RotateCcw } from 'lucide-react'
import { useCallback } from 'react'
import { cn } from '@/lib/utils'
import type { Persona, PersonaUpdate } from '@/types/persona'

const RESET_MODES = [
  {
    value: 'off',
    label: 'Off',
    description: 'Sessions persist until manually cleared',
  },
  {
    value: 'daily',
    label: 'Daily',
    description: 'Reset at a specific hour each day',
  },
  {
    value: 'idle',
    label: 'Idle',
    description: 'Reset after inactivity timeout',
  },
] as const

const HOUR_OPTIONS = Array.from({ length: 24 }, (_, i) => {
  const h = i % 12 || 12
  const suffix = i < 12 ? 'AM' : 'PM'
  return { value: i, label: `${h}:00 ${suffix}` }
})

const IDLE_PRESETS = [
  { value: 30, label: '30 min' },
  { value: 60, label: '1 hour' },
  { value: 120, label: '2 hours' },
  { value: 240, label: '4 hours' },
  { value: 480, label: '8 hours' },
]

const DEFAULT_LIMITS: Record<
  string,
  { label: string; description: string; value: number }
> = {
  max_turns: {
    label: 'Max turns',
    description:
      'Maximum agent turns per execution. Soft limit at 50%, checkpoints every 25%, wrap-up at limit, grace period for cleanup.',
    value: 500,
  },
}

interface SessionLimitsTabProps {
  persona: Persona
  onUpdate: (fields: PersonaUpdate) => void
}

export function SessionLimitsTab({ persona, onUpdate }: SessionLimitsTabProps) {
  const mode = persona.session_reset_mode || 'off'

  const handleModeChange = useCallback(
    (newMode: 'off' | 'daily' | 'idle') => {
      onUpdate({ session_reset_mode: newMode })
    },
    [onUpdate],
  )

  const handleHourChange = useCallback(
    (hour: number) => {
      onUpdate({ session_reset_hour: hour })
    },
    [onUpdate],
  )

  const handleIdleChange = useCallback(
    (minutes: number) => {
      onUpdate({ session_reset_idle_minutes: minutes })
    },
    [onUpdate],
  )

  const handleLimitChange = useCallback(
    (key: string, value: number) => {
      const current = persona.limits || {}
      onUpdate({ limits: { ...current, [key]: value } })
    },
    [onUpdate, persona.limits],
  )

  const handleLimitReset = useCallback(
    (key: string) => {
      if (!persona.limits) return
      const next = { ...persona.limits }
      delete next[key]
      onUpdate({ limits: Object.keys(next).length > 0 ? next : null })
    },
    [onUpdate, persona.limits],
  )

  const getLimitValue = (key: string): number => {
    return persona.limits?.[key] ?? DEFAULT_LIMITS[key].value
  }

  const isLimitCustom = (key: string): boolean => {
    return (
      persona.limits?.[key] != null &&
      persona.limits[key] !== DEFAULT_LIMITS[key].value
    )
  }

  return (
    <div className="space-y-8">
      <div>
        <p className="section-kicker">Session Lifecycles</p>
        <h2 className="section-heading mt-2">Reset Policy & Limits</h2>
        <p className="section-copy mt-2 max-w-3xl">
          Control when long-running conversations roll over and set the safety
          limits that shape autonomous execution length.
        </p>
      </div>

      <div className="space-y-4 section-card">
        <div>
          <h2 className="section-heading">Session Reset</h2>
          <p className="section-copy mt-2">
            Control when conversation sessions automatically reset.
          </p>
        </div>

        {/* Mode Selector — segmented control */}
        <div className="segmented-control max-w-md">
          {RESET_MODES.map((opt) => (
            <button
              key={opt.value}
              type="button"
              onClick={() => handleModeChange(opt.value)}
              className={cn(
                'segmented-option flex-1 justify-center',
                mode === opt.value
                  ? 'border-amber-500/20 bg-amber-500/12 text-amber-100'
                  : 'hover:border-slate-700/80 hover:bg-slate-900/80 hover:text-slate-200',
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>

        {/* Mode Description + Controls */}
        <div className="detail-card max-w-md">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={cn(
                'w-2 h-2 rounded-full flex-shrink-0',
                mode === 'off' ? 'bg-slate-400' : 'bg-emerald-500',
              )}
            />
            <p className="text-sm font-medium text-slate-300">
              {RESET_MODES.find((m) => m.value === mode)?.description}
            </p>
          </div>

          {mode === 'daily' && (
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-slate-400">Reset hour</span>
              <select
                aria-label="Session reset hour"
                value={persona.session_reset_hour}
                onChange={(e) => handleHourChange(Number(e.target.value))}
                className="control-select"
              >
                {HOUR_OPTIONS.map((h) => (
                  <option key={h.value} value={h.value}>
                    {h.label}
                  </option>
                ))}
              </select>
            </div>
          )}

          {mode === 'idle' && (
            <div className="mt-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-400">Idle timeout</span>
                <span className="text-xs font-mono text-slate-400">
                  {persona.session_reset_idle_minutes} min
                </span>
              </div>
              <div className="flex gap-1">
                {IDLE_PRESETS.map((preset) => (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => handleIdleChange(preset.value)}
                    className={cn(
                      'flex-1 rounded-xl border px-2 py-1.5 text-xs transition-colors',
                      persona.session_reset_idle_minutes === preset.value
                        ? 'border-amber-500/20 bg-amber-500/12 text-amber-100 font-medium'
                        : 'border-slate-700/80 text-slate-400 hover:bg-slate-900/80',
                    )}
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Limits Section */}
      <div className="space-y-4 section-card">
        <div>
          <h2 className="section-heading">Limits</h2>
          <p className="section-copy mt-2">
            Configurable limits for autonomous operations. Leave at defaults for
            normal use.
          </p>
        </div>

        <div className="space-y-3 max-w-md">
          {Object.entries(DEFAULT_LIMITS).map(([key, config]) => (
            <div key={key} className="detail-card">
              <div className="flex items-center justify-between mb-1">
                <label className="detail-label">{config.label}</label>
                {isLimitCustom(key) && (
                  <button
                    type="button"
                    onClick={() => handleLimitReset(key)}
                    className="flex items-center gap-1 text-[10px] text-amber-400 hover:text-amber-300 transition-colors cursor-pointer"
                  >
                    <RotateCcw className="w-2.5 h-2.5" />
                    Reset
                  </button>
                )}
              </div>
              <p className="text-[10px] text-slate-500 mb-2">
                {config.description}
              </p>
              <input
                aria-label={config.label}
                type="number"
                value={getLimitValue(key)}
                onChange={(e) => {
                  const v = Number.parseInt(e.target.value, 10)
                  if (!Number.isNaN(v) && v >= 1) handleLimitChange(key, v)
                }}
                min={1}
                placeholder={String(config.value)}
                className="control-input font-mono"
              />
              {!isLimitCustom(key) && (
                <p className="text-[10px] text-slate-400 mt-1">
                  Default: {config.value}
                </p>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
