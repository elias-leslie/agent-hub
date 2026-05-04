'use client'

import type { Agent, ModelInfo } from '../types'
import { FallbackModelsList } from './FallbackModelsList'
import { ModelSelect } from './ModelSelect'

interface ModelsTabProps {
  formData: Partial<Agent>
  availableModels: ModelInfo[]
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
}

export function ModelsTab({
  formData,
  availableModels,
  updateField,
}: ModelsTabProps) {
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

      <div className="space-y-6">
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
