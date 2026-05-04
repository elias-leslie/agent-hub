'use client'

import { Loader2, PlayCircle } from 'lucide-react'
import { useMemo, useState } from 'react'
import { fetchApi } from '@/lib/api-config'
import type {
  Agent,
  CommitteeConfig,
  CommitteeSeatConfig,
  ModelInfo,
} from '../types'

const DEFAULT_COMMITTEE_CONFIG: CommitteeConfig = {
  orchestrator: {
    agent_slug: 'investment-committee',
    model_id: null,
    instruction: 'Synthesize committee votes into the final market call.',
  },
  seats: [
    {
      key: 'macro',
      label: 'Macro',
      enabled: true,
      agent_slug: 'market-pulse-analyst',
      model_id: null,
      instruction:
        'Focus on macro regime, rates, breadth, and options positioning.',
      weight: 1,
    },
    {
      key: 'cross_asset',
      label: 'Cross-Asset',
      enabled: true,
      agent_slug: 'equity-analyst',
      model_id: null,
      instruction:
        'Stress-test policy, cross-asset leadership, and narrative drift.',
      weight: 1,
    },
    {
      key: 'risk',
      label: 'Risk',
      enabled: true,
      agent_slug: 'risk-manager',
      model_id: null,
      instruction: 'Challenge downside tails, uncertainty, and failure modes.',
      weight: 1,
    },
  ],
}

function resolveCommitteeConfig(formData: Partial<Agent>): CommitteeConfig {
  const candidate = formData.strategies?.committee
  if (!candidate) return structuredClone(DEFAULT_COMMITTEE_CONFIG)
  return {
    orchestrator: {
      ...DEFAULT_COMMITTEE_CONFIG.orchestrator,
      ...(candidate.orchestrator ?? {}),
    },
    seats: candidate.seats?.length
      ? candidate.seats
      : structuredClone(DEFAULT_COMMITTEE_CONFIG.seats),
  }
}

interface CommitteeTabProps {
  formData: Partial<Agent>
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
  availableModels: ModelInfo[]
}

export function CommitteeTab({
  formData,
  updateField,
  availableModels,
}: CommitteeTabProps) {
  const [isRunning, setIsRunning] = useState(false)
  const [validationHeadline, setValidationHeadline] = useState<string | null>(
    null,
  )
  const [validationError, setValidationError] = useState<string | null>(null)
  const [validationResult, setValidationResult] = useState<Record<
    string,
    any
  > | null>(null)
  const committee = useMemo(() => resolveCommitteeConfig(formData), [formData])

  const persistCommittee = (nextCommittee: CommitteeConfig) => {
    updateField('strategies', {
      ...(formData.strategies ?? {}),
      committee: nextCommittee,
    } as Agent['strategies'])
  }

  const updateSeat = (
    seatKey: string,
    updates: Partial<CommitteeSeatConfig>,
  ) => {
    persistCommittee({
      ...committee,
      seats: committee.seats.map((seat) =>
        seat.key === seatKey ? { ...seat, ...updates } : seat,
      ),
    })
  }

  const updateOrchestrator = (
    field: keyof CommitteeConfig['orchestrator'],
    value: string,
  ) => {
    persistCommittee({
      ...committee,
      orchestrator: {
        ...committee.orchestrator,
        [field]: value || null,
      },
    })
  }

  const runValidation = async () => {
    setIsRunning(true)
    setValidationError(null)
    setValidationResult(null)
    try {
      const response = await fetchApi('/api/orchestration/committee', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prompt: 'Run a validation roundtable for SPY and sector forecasts.',
          window_days: 3,
          source_snapshot: { target_universe: ['SPY', 'XLK', 'XLF'] },
          agent_slug: 'investment-committee',
        }),
      })
      if (!response.ok) {
        throw new Error('Failed to run validation roundtable')
      }
      const payload = await response.json()
      setValidationResult(payload)
      setValidationHeadline(
        payload.committee_summary?.headline ?? 'Validation completed.',
      )
    } catch (error) {
      setValidationError(
        error instanceof Error ? error.message : 'Validation failed',
      )
    } finally {
      setIsRunning(false)
    }
  }

  return (
    <div className="space-y-6">
      <section className="rounded-3xl border border-amber-500/20 bg-[radial-gradient(circle_at_top_left,_rgba(245,158,11,0.16),_transparent_32%),linear-gradient(180deg,rgba(17,24,39,0.96),rgba(2,6,23,0.96))] p-6 shadow-[0_0_30px_-16px_rgba(245,158,11,0.5)]">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
          <div>
            <p className="section-kicker">Committee Control Plane</p>
            <h3 className="mt-2 text-2xl font-semibold text-slate-100">
              Market Prediction Committee
            </h3>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-400">
              Configure the roundtable roster that Portfolio AI uses for market
              forecasts, then validate the live seat mix against the current
              backend committee endpoint.
            </p>
          </div>
          <button
            type="button"
            onClick={() => void runValidation()}
            disabled={isRunning}
            className="inline-flex items-center gap-2 rounded-2xl border border-amber-400/30 bg-amber-500/10 px-4 py-3 text-sm font-medium text-amber-100 transition hover:bg-amber-500/15 disabled:opacity-60"
          >
            {isRunning ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <PlayCircle className="h-4 w-4" />
            )}
            Run validation roundtable
          </button>
        </div>
        {validationHeadline ? (
          <p className="mt-4 rounded-2xl border border-emerald-500/20 bg-emerald-500/10 px-4 py-3 text-sm text-emerald-100">
            {validationHeadline}
          </p>
        ) : null}
        {validationResult ? (
          <div className="mt-4 rounded-2xl border border-cyan-500/20 bg-cyan-500/10 p-4 text-sm text-cyan-50">
            <p className="section-kicker">Validation snapshot</p>
            <div className="mt-3 grid gap-3 sm:grid-cols-3">
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/70">
                  Committee bias
                </p>
                <p className="mt-1 text-sm font-medium text-cyan-50">
                  {validationResult.committee_summary?.headline ??
                    validationHeadline ??
                    'Validation completed.'}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/70">
                  Seat count
                </p>
                <p className="mt-1 text-sm font-medium text-cyan-50">
                  {validationResult.committee_summary?.seat_count ??
                    validationResult.votes?.length ??
                    0}
                </p>
              </div>
              <div>
                <p className="text-[11px] uppercase tracking-[0.24em] text-cyan-200/70">
                  Disagreement
                </p>
                <p className="mt-1 text-sm font-medium text-cyan-50">
                  {validationResult.committee_summary?.disagreement_label ??
                    'n/a'}
                </p>
              </div>
            </div>
          </div>
        ) : null}
        {validationError ? (
          <p className="mt-4 rounded-2xl border border-rose-500/20 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
            {validationError}
          </p>
        ) : null}
      </section>

      <section className="rounded-3xl border border-slate-800/80 bg-slate-950/60 p-6">
        <div className="grid gap-4 xl:grid-cols-3">
          <div className="xl:col-span-3">
            <p className="section-kicker">Orchestrator</p>
          </div>
          <label className="space-y-2 text-sm text-slate-300">
            <span>Orchestrator agent slug</span>
            <input
              value={committee.orchestrator.agent_slug}
              onChange={(event) =>
                updateOrchestrator('agent_slug', event.target.value)
              }
              className="w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
            />
          </label>
          <label className="space-y-2 text-sm text-slate-300">
            <span>Orchestrator model</span>
            <select
              value={committee.orchestrator.model_id ?? ''}
              onChange={(event) =>
                updateOrchestrator('model_id', event.target.value)
              }
              className="w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
            >
              <option value="">Use agent default</option>
              {availableModels.map((model) => (
                <option key={model.id} value={model.id}>
                  {model.name}
                </option>
              ))}
            </select>
          </label>
          <label className="space-y-2 text-sm text-slate-300 xl:col-span-1">
            <span>Orchestrator instruction</span>
            <textarea
              value={committee.orchestrator.instruction ?? ''}
              onChange={(event) =>
                updateOrchestrator('instruction', event.target.value)
              }
              className="min-h-[112px] w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
            />
          </label>
        </div>
      </section>

      <div className="grid gap-4 xl:grid-cols-3">
        {committee.seats.map((seat) => (
          <section
            key={seat.key}
            className="rounded-3xl border border-slate-800/80 bg-slate-950/60 p-5"
          >
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="section-kicker">Seat</p>
                <h4 className="mt-2 text-lg font-semibold text-slate-100">
                  {seat.label}
                </h4>
              </div>
              <label className="inline-flex items-center gap-2 text-sm text-slate-300">
                <input
                  type="checkbox"
                  checked={seat.enabled}
                  onChange={(event) =>
                    updateSeat(seat.key, { enabled: event.target.checked })
                  }
                />
                Enabled
              </label>
            </div>

            <div className="mt-4 space-y-4">
              <label className="space-y-2 text-sm text-slate-300">
                <span>{seat.label} seat agent slug</span>
                <input
                  value={seat.agent_slug}
                  onChange={(event) =>
                    updateSeat(seat.key, { agent_slug: event.target.value })
                  }
                  className="w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
                />
              </label>

              <label className="space-y-2 text-sm text-slate-300">
                <span>{seat.label} seat model</span>
                <select
                  aria-label={`${seat.label} seat model`}
                  value={seat.model_id ?? ''}
                  onChange={(event) =>
                    updateSeat(seat.key, {
                      model_id: event.target.value || null,
                    })
                  }
                  className="w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
                >
                  <option value="">Use agent default</option>
                  {availableModels.map((model) => (
                    <option key={model.id} value={model.id}>
                      {model.name}
                    </option>
                  ))}
                </select>
              </label>

              <label className="space-y-2 text-sm text-slate-300">
                <span>{seat.label} rubric override</span>
                <textarea
                  value={seat.instruction ?? ''}
                  onChange={(event) =>
                    updateSeat(seat.key, { instruction: event.target.value })
                  }
                  className="min-h-[112px] w-full rounded-2xl border border-slate-800 bg-slate-950 px-3 py-2 text-slate-100"
                />
              </label>
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
