'use client'

import { Gauge, Route } from 'lucide-react'
import { useMemo, useState } from 'react'
import type {
  Agent,
  AgentRouting,
  AgentRoutingUpdate,
  ModelInfo,
  RoutingMode,
  RoutingRiskTier,
  WorkloadRoutingUpdate,
} from '../types'
import { FallbackModelsList } from './FallbackModelsList'
import { ModelSelect } from './ModelSelect'

interface ModelsTabProps {
  formData: Partial<Agent>
  availableModels: ModelInfo[]
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
  routing?: AgentRouting
  isRoutingSaving?: boolean
  onRoutingChange?: (data: AgentRoutingUpdate) => void
  onWorkloadRoutingChange?: (
    workloadProfile: string,
    data: WorkloadRoutingUpdate,
  ) => void
}

const ROUTING_MODES: Array<{ value: RoutingMode; label: string }> = [
  { value: 'manual_locked', label: 'Manual lock' },
  { value: 'auto_shadow', label: 'Shadow' },
  { value: 'auto_canary', label: 'Canary' },
  { value: 'auto', label: 'Auto' },
]

const RISK_TIERS: Array<{ value: RoutingRiskTier; label: string }> = [
  { value: 'low', label: 'Low' },
  { value: 'normal', label: 'Normal' },
  { value: 'elevated', label: 'Elevated' },
  { value: 'critical', label: 'Critical' },
]

function clampPercent(value: string): number {
  const parsed = Number(value)
  if (!Number.isFinite(parsed)) return 0
  return Math.max(0, Math.min(100, parsed))
}

export function ModelsTab({
  formData,
  availableModels,
  updateField,
  routing,
  isRoutingSaving = false,
  onRoutingChange,
  onWorkloadRoutingChange,
}: ModelsTabProps) {
  const profileLabelByKey = useMemo(
    () =>
      new Map(
        routing?.workload_profiles.map((profile) => [
          profile.key,
          profile.label,
        ]) ?? [],
      ),
    [routing],
  )
  const [workloadKey, setWorkloadKey] = useState('')
  const [workloadMode, setWorkloadMode] = useState<RoutingMode>('auto_canary')
  const [workloadCanary, setWorkloadCanary] = useState('5')
  const selectedWorkloadKey =
    workloadKey || routing?.workload_profiles[0]?.key || 'general'

  const updateProfile = (data: AgentRoutingUpdate) => {
    if (!onRoutingChange || isRoutingSaving) return
    onRoutingChange(data)
  }

  const updateWorkload = (
    workloadProfile: string,
    data: WorkloadRoutingUpdate,
  ) => {
    if (!onWorkloadRoutingChange || isRoutingSaving) return
    onWorkloadRoutingChange(workloadProfile, data)
  }

  return (
    <div className="space-y-6">
      <div className="section-header">
        <div>
          <p className="section-kicker">Model Routing</p>
          <h2 className="section-heading mt-2">Model Configuration</h2>
          <p className="section-copy mt-2 max-w-3xl">
            Choose the primary runtime model, define fallback order, and
            optionally set an escalation model for higher-complexity tasks.
          </p>
        </div>
      </div>

      {routing && (
        <div className="section-card space-y-5">
          <div className="section-header">
            <div>
              <p className="section-kicker">Adaptive Router</p>
              <h3 className="section-heading mt-2">Agent Policy</h3>
            </div>
            {isRoutingSaving ? (
              <span className="page-pill">Saving</span>
            ) : (
              <span className="page-pill">Live</span>
            )}
          </div>

          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Mode</span>
              <select
                className="control-select w-full"
                value={routing.default_routing_mode}
                disabled={isRoutingSaving}
                onChange={(event) =>
                  updateProfile({
                    default_routing_mode: event.target.value as RoutingMode,
                  })
                }
              >
                {ROUTING_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Risk</span>
              <select
                className="control-select w-full"
                value={routing.risk_tier}
                disabled={isRoutingSaving}
                onChange={(event) =>
                  updateProfile({
                    risk_tier: event.target.value as RoutingRiskTier,
                  })
                }
              >
                {RISK_TIERS.map((risk) => (
                  <option key={risk.value} value={risk.value}>
                    {risk.label}
                  </option>
                ))}
              </select>
            </label>

            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Quality floor</span>
              <input
                className="control-input"
                type="number"
                min={0}
                max={100}
                defaultValue={routing.quality_floor ?? ''}
                disabled={isRoutingSaving}
                onBlur={(event) =>
                  updateProfile({
                    quality_floor:
                      event.target.value === ''
                        ? null
                        : clampPercent(event.target.value),
                  })
                }
              />
            </label>

            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Exploration</span>
              <input
                className="control-input"
                defaultValue={routing.exploration_policy}
                disabled={isRoutingSaving}
                onBlur={(event) =>
                  updateProfile({ exploration_policy: event.target.value })
                }
              />
            </label>
          </div>

          <div className="rounded-xl border border-slate-800/70">
            <div className="grid grid-cols-[1.1fr_0.8fr_0.55fr_0.45fr] gap-2 border-b border-slate-800/70 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <span>Workload</span>
              <span>Mode</span>
              <span>Canary</span>
              <span>Enabled</span>
            </div>
            <div className="divide-y divide-slate-800/70">
              {routing.workload_overrides.length === 0 ? (
                <div className="px-3 py-4 text-sm text-slate-500">
                  No workload overrides
                </div>
              ) : (
                routing.workload_overrides.map((override) => (
                  <div
                    key={override.workload_profile}
                    className="grid grid-cols-[1.1fr_0.8fr_0.55fr_0.45fr] items-center gap-2 px-3 py-2 text-sm"
                  >
                    <span className="min-w-0 truncate text-slate-200">
                      {profileLabelByKey.get(override.workload_profile) ??
                        override.workload_profile}
                    </span>
                    <select
                      className="control-select w-full py-1.5"
                      value={override.routing_mode}
                      disabled={isRoutingSaving}
                      onChange={(event) =>
                        updateWorkload(override.workload_profile, {
                          routing_mode: event.target.value as RoutingMode,
                          canary_percent: override.canary_percent,
                          reason: override.reason,
                          owner: override.owner,
                          enabled: override.enabled,
                        })
                      }
                    >
                      {ROUTING_MODES.map((mode) => (
                        <option key={mode.value} value={mode.value}>
                          {mode.label}
                        </option>
                      ))}
                    </select>
                    <input
                      className="control-input py-1.5"
                      type="number"
                      min={0}
                      max={100}
                      defaultValue={override.canary_percent}
                      disabled={isRoutingSaving}
                      onBlur={(event) =>
                        updateWorkload(override.workload_profile, {
                          routing_mode: override.routing_mode,
                          canary_percent: clampPercent(event.target.value),
                          reason: override.reason,
                          owner: override.owner,
                          enabled: override.enabled,
                        })
                      }
                    />
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber-500"
                      checked={override.enabled}
                      disabled={isRoutingSaving}
                      onChange={(event) =>
                        updateWorkload(override.workload_profile, {
                          routing_mode: override.routing_mode,
                          canary_percent: override.canary_percent,
                          reason: override.reason,
                          owner: override.owner,
                          enabled: event.target.checked,
                        })
                      }
                    />
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-[1.2fr_0.8fr_0.5fr_auto]">
            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Workload</span>
              <select
                className="control-select w-full"
                value={selectedWorkloadKey}
                disabled={isRoutingSaving}
                onChange={(event) => setWorkloadKey(event.target.value)}
              >
                {routing.workload_profiles.map((profile) => (
                  <option key={profile.key} value={profile.key}>
                    {profile.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Mode</span>
              <select
                className="control-select w-full"
                value={workloadMode}
                disabled={isRoutingSaving}
                onChange={(event) =>
                  setWorkloadMode(event.target.value as RoutingMode)
                }
              >
                {ROUTING_MODES.map((mode) => (
                  <option key={mode.value} value={mode.value}>
                    {mode.label}
                  </option>
                ))}
              </select>
            </label>
            <label className="space-y-2 text-sm">
              <span className="text-slate-300">Canary</span>
              <input
                className="control-input"
                value={workloadCanary}
                disabled={isRoutingSaving}
                onChange={(event) => setWorkloadCanary(event.target.value)}
              />
            </label>
            <button
              type="button"
              className="button-secondary self-end"
              disabled={isRoutingSaving || !selectedWorkloadKey}
              onClick={() =>
                updateWorkload(selectedWorkloadKey, {
                  routing_mode: workloadMode,
                  canary_percent: clampPercent(workloadCanary),
                  reason: 'Routing policy override',
                  owner: 'agent-hub-ui',
                  enabled: true,
                })
              }
            >
              <Route className="h-4 w-4" />
              Apply
            </button>
          </div>
        </div>
      )}

      <div className="space-y-6">
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Gauge className="h-4 w-4" />
          Manual chain
        </div>
        <ModelSelect
          label="Primary Model"
          description="The default model used for normal execution."
          value={formData.primary_model_id ?? null}
          onChange={(v) => updateField('primary_model_id', v ?? '')}
          models={availableModels}
        />

        <FallbackModelsList
          selectedModels={formData.fallback_models ?? []}
          availableModels={availableModels}
          onChange={(models) => updateField('fallback_models', models)}
        />

        <ModelSelect
          label="Escalation Model (for complex tasks)"
          description="Optional upgrade path for difficult prompts or higher-scrutiny workflows."
          value={formData.escalation_model_id ?? null}
          onChange={(v) => updateField('escalation_model_id', v)}
          models={availableModels}
          allowNull
        />
      </div>
    </div>
  )
}
