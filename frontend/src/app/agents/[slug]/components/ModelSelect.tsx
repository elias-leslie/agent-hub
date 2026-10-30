import { getProviderInfo } from '@/components/settings/constants'
import type { ModelInfo } from '../types'

/** Option text per model id; a name two providers share (Codex and OpenAI 'GPT-6.1 Terra') gets its provider. */
export function modelOptionLabels(models: ModelInfo[]): Map<string, string> {
  const seen = new Map<string, number>()
  for (const model of models)
    seen.set(model.name, (seen.get(model.name) ?? 0) + 1)
  return new Map(
    models.map((model) => [
      model.id,
      (seen.get(model.name) ?? 0) > 1
        ? `${model.name} (${getProviderInfo(model.provider).name})`
        : model.name,
    ]),
  )
}

interface ModelSelectProps {
  value: string | null
  onChange: (value: string | null) => void
  label: string
  description?: string
  models: ModelInfo[]
  allowNull?: boolean
}

export function ModelSelect({
  value,
  onChange,
  label,
  description,
  models,
  allowNull = false,
}: ModelSelectProps) {
  const routableModels = models.filter((model) => model.routable)
  const labels = modelOptionLabels(routableModels)

  return (
    <div className="section-card space-y-3">
      <div>
        <label className="detail-label">{label}</label>
        {description ? (
          <p className="mt-2 text-sm text-slate-400">{description}</p>
        ) : null}
      </div>
      <select
        value={value ?? ''}
        onChange={(e) => onChange(e.target.value || null)}
        className="control-select w-full"
      >
        {allowNull && <option value="">None</option>}
        {routableModels.map((model) => (
          <option key={model.id} value={model.id}>
            {labels.get(model.id)}
          </option>
        ))}
      </select>
    </div>
  )
}
