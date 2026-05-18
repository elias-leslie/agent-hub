import { useEffect, useState } from 'react'
import type { Agent, ModelInfo } from '../types'

interface ParametersTabProps {
  formData: Partial<Agent>
  availableModels: ModelInfo[]
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
}

interface LimitFieldConfig {
  field:
    | 'max_concurrency'
    | 'max_subagent_concurrency'
    | 'daily_token_budget'
    | 'hourly_request_limit'
  label: string
  min: number
  max?: number
  placeholder: string
  description: string
}

type NumericField = LimitFieldConfig['field']
type DraftState = Record<NumericField, string>
type ErrorState = Partial<Record<NumericField, string>>

const LIMIT_FIELDS: readonly LimitFieldConfig[] = [
  {
    field: 'max_concurrency',
    label: 'Max concurrency',
    min: 1,
    max: 100,
    placeholder: 'Default pool',
    description:
      'Maximum parallel executions for this agent. Leave empty to use the system default.',
  },
  {
    field: 'max_subagent_concurrency',
    label: 'Max subagent concurrency',
    min: 1,
    max: 100,
    placeholder: 'Default pool',
    description:
      'Cap parallel subagent spawns. Useful for containing fan-out during large workflows.',
  },
  {
    field: 'daily_token_budget',
    label: 'Daily token budget',
    min: 0,
    placeholder: 'Unlimited',
    description:
      'Per-agent daily token ceiling. Use 0 for unlimited, or leave empty to defer to platform policy.',
  },
  {
    field: 'hourly_request_limit',
    label: 'Hourly request limit',
    min: 0,
    placeholder: 'Unlimited',
    description:
      'Per-agent request cap each hour. Use 0 for unlimited, or leave empty to defer to platform policy.',
  },
] as const

function parseOptionalInteger(
  rawValue: string,
  min: number,
  max?: number,
): number | null | undefined {
  if (rawValue === '') {
    return null
  }

  const value = Number.parseInt(rawValue, 10)
  if (
    Number.isNaN(value) ||
    value < min ||
    (max !== undefined && value > max)
  ) {
    return undefined
  }

  return value
}

function formatDraftValue(value: number | null | undefined): string {
  return value == null ? '' : String(value)
}

const THINKING_LEVELS = [
  { value: '', label: 'Off (default)', hint: 'No extended reasoning' },
  {
    value: 'none',
    label: 'None',
    hint: 'Explicitly disable reasoning (OpenAI)',
  },
  {
    value: 'minimal',
    label: 'Minimal',
    hint: 'Light reasoning for simple tasks',
  },
  { value: 'low', label: 'Low', hint: 'Basic reasoning, fast responses' },
  {
    value: 'medium',
    label: 'Medium',
    hint: 'Balanced reasoning for most tasks',
  },
  { value: 'high', label: 'High', hint: 'Deep reasoning for complex analysis' },
  { value: 'xhigh', label: 'xHigh', hint: 'Maximum reasoning (GPT-5.4/5.5)' },
] as const

const VERBOSITY_LEVELS = [
  { value: '', label: 'Default', hint: 'Model decides output length' },
  { value: 'low', label: 'Low', hint: 'Minimal output, no extra comments' },
  {
    value: 'medium',
    label: 'Medium',
    hint: 'Explanatory comments and structure',
  },
  {
    value: 'high',
    label: 'High',
    hint: 'Comprehensive, production-ready output',
  },
] as const

function getSelectedModel(
  availableModels: ModelInfo[],
  modelId: string | null | undefined,
): ModelInfo | null {
  if (!modelId) {
    return null
  }
  return availableModels.find((model) => model.id === modelId) ?? null
}

export function ParametersTab({
  formData,
  availableModels,
  updateField,
}: ParametersTabProps) {
  const [draftValues, setDraftValues] = useState<DraftState>({
    max_concurrency: formatDraftValue(formData.max_concurrency),
    max_subagent_concurrency: formatDraftValue(
      formData.max_subagent_concurrency,
    ),
    daily_token_budget: formatDraftValue(formData.daily_token_budget),
    hourly_request_limit: formatDraftValue(formData.hourly_request_limit),
  })
  const [fieldErrors, setFieldErrors] = useState<ErrorState>({})

  useEffect(() => {
    setDraftValues({
      max_concurrency: formatDraftValue(formData.max_concurrency),
      max_subagent_concurrency: formatDraftValue(
        formData.max_subagent_concurrency,
      ),
      daily_token_budget: formatDraftValue(formData.daily_token_budget),
      hourly_request_limit: formatDraftValue(formData.hourly_request_limit),
    })
  }, [
    formData.daily_token_budget,
    formData.hourly_request_limit,
    formData.max_concurrency,
    formData.max_subagent_concurrency,
  ])

  function updateDraft(field: NumericField, rawValue: string) {
    setDraftValues((current) => ({ ...current, [field]: rawValue }))
  }

  function clearFieldError(field: NumericField) {
    setFieldErrors((current) => {
      if (!current[field]) {
        return current
      }
      const next = { ...current }
      delete next[field]
      return next
    })
  }

  function setFieldError(field: NumericField, message: string) {
    setFieldErrors((current) => ({ ...current, [field]: message }))
  }

  const selectedModel = getSelectedModel(
    availableModels,
    formData.primary_model_id,
  )
  const supportsThinking = selectedModel?.capabilities.has_thinking ?? false
  const supportsVerbosity =
    selectedModel?.capabilities.supports_verbosity ?? false
  const thinkingLevels = THINKING_LEVELS.filter(
    (level) =>
      level.value !== 'xhigh' || selectedModel?.capabilities.supports_xhigh,
  )

  return (
    <div className="space-y-6">
      <div className="section-header">
        <div>
          <p className="section-kicker">Generation Controls</p>
          <h2 className="section-heading mt-2">Generation Parameters</h2>
          <p className="section-copy mt-2 max-w-3xl">
            Tune creativity, reasoning depth, verbosity, and execution budgets
            for this agent&apos;s runtime profile.
          </p>
        </div>
      </div>

      <div className="space-y-6">
        <div className="section-card space-y-2">
          <div className="flex items-center justify-between">
            <label htmlFor="temperature" className="detail-label">
              Temperature
            </label>
            <span className="text-sm font-mono text-slate-300">
              {(formData.temperature ?? 0.7).toFixed(2)}
            </span>
          </div>
          <input
            id="temperature"
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={formData.temperature ?? 0.7}
            onChange={(e) =>
              updateField('temperature', parseFloat(e.target.value))
            }
            className="h-2 w-full cursor-pointer appearance-none rounded-lg bg-slate-800 accent-amber-500"
          />
          <div className="flex justify-between text-[10px] text-slate-400">
            <span>Precise (0)</span>
            <span>Balanced (1)</span>
            <span>Creative (2)</span>
          </div>
        </div>

        {supportsThinking ? (
          <div className="section-card space-y-2">
            <label htmlFor="thinking_level" className="detail-label">
              Thinking Level
            </label>
            <select
              id="thinking_level"
              value={formData.thinking_level ?? ''}
              onChange={(e) =>
                updateField('thinking_level', e.target.value || null)
              }
              className="control-select w-full"
            >
              {thinkingLevels.map((level) => (
                <option key={level.value} value={level.value}>
                  {level.label} — {level.hint}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-slate-400">
              Controls reasoning depth. Higher levels produce more thorough but
              slower responses. Unsupported levels are hidden per model.
            </p>
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-800/80 bg-slate-950/60 px-4 py-3 text-sm text-slate-400">
            This model does not support configurable reasoning effort.
          </div>
        )}

        {supportsVerbosity ? (
          <div className="section-card space-y-2">
            <label htmlFor="verbosity_level" className="detail-label">
              Verbosity Level
            </label>
            <select
              id="verbosity_level"
              value={formData.verbosity_level ?? ''}
              onChange={(e) =>
                updateField('verbosity_level', e.target.value || null)
              }
              className="control-select w-full"
            >
              {VERBOSITY_LEVELS.map((level) => (
                <option key={level.value} value={level.value}>
                  {level.label} — {level.hint}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-slate-400">
              Controls output length and detail for models that expose a
              verbosity knob.
            </p>
          </div>
        ) : (
          <div className="rounded-2xl border border-slate-800/80 bg-slate-950/60 px-4 py-3 text-sm text-slate-400">
            This model ignores verbosity overrides.
          </div>
        )}

        <div className="section-card space-y-4">
          <div>
            <h3 className="section-heading text-sm">Execution limits</h3>
            <p className="mt-2 text-xs text-slate-400">
              Agent-specific caps for concurrency, request volume, and spend
              controls.
            </p>
          </div>

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {LIMIT_FIELDS.map((config) => (
              <div key={config.field} className="detail-card space-y-2">
                <label htmlFor={config.field} className="detail-label">
                  {config.label}
                </label>
                <input
                  id={config.field}
                  aria-label={config.label}
                  type="number"
                  min={config.min}
                  max={config.max}
                  placeholder={config.placeholder}
                  aria-invalid={fieldErrors[config.field] ? 'true' : 'false'}
                  value={draftValues[config.field]}
                  onChange={(e) => {
                    updateDraft(config.field, e.target.value)
                    const value = parseOptionalInteger(
                      e.target.value,
                      config.min,
                      config.max,
                    )
                    if (value !== undefined) {
                      clearFieldError(config.field)
                      updateField(
                        config.field,
                        value as Agent[typeof config.field],
                      )
                    } else {
                      const maxText =
                        config.max !== undefined ? ` and ${config.max}` : ''
                      setFieldError(
                        config.field,
                        `Enter a whole number between ${config.min}${maxText}.`,
                      )
                    }
                  }}
                  className="control-input font-mono"
                />
                <p className="text-[10px] text-slate-400">
                  {config.description}
                </p>
                {fieldErrors[config.field] && (
                  <p className="text-[10px] text-rose-500">
                    {fieldErrors[config.field]}
                  </p>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}
