import type { ModelInfo } from '../types'

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
            {model.name}
          </option>
        ))}
      </select>
    </div>
  )
}
