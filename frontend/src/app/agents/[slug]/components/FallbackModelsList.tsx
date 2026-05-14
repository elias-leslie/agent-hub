import { Plus, Trash2 } from 'lucide-react'
import type { ModelInfo } from '../types'

interface FallbackModelsListProps {
  selectedModels: string[]
  availableModels: ModelInfo[]
  onChange: (models: string[]) => void
}

export function FallbackModelsList({
  selectedModels,
  availableModels,
  onChange,
}: FallbackModelsListProps) {
  const routableModels = availableModels.filter((model) => model.routable)

  const addModel = () => {
    const available = routableModels.filter(
      (m) => !selectedModels.includes(m.id),
    )
    if (available.length > 0) {
      onChange([...selectedModels, available[0].id])
    }
  }

  const removeModel = (index: number) => {
    onChange(selectedModels.filter((_, i) => i !== index))
  }

  const updateModel = (index: number, value: string) => {
    const updated = [...selectedModels]
    updated[index] = value
    onChange(updated)
  }

  return (
    <div className="section-card space-y-3">
      <div>
        <label className="detail-label">Fallback Models (in order)</label>
        <p className="mt-2 text-sm text-slate-400">
          Define the ordered fallback chain used when the primary model is
          unavailable.
        </p>
      </div>
      {selectedModels.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-slate-700/80 bg-slate-950/60 px-4 py-4 text-sm text-slate-400">
          No fallback models configured yet.
        </div>
      ) : (
        <div className="space-y-2">
          {selectedModels.map((model, index) => (
            <div key={index} className="flex items-center gap-2">
              <select
                value={model}
                onChange={(e) => updateModel(index, e.target.value)}
                className="control-select flex-1"
              >
                {routableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => removeModel(index)}
                className="icon-button h-10 w-10 border-rose-500/20 bg-rose-500/10 text-rose-200 hover:bg-rose-500/15"
                aria-label="Remove model"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        onClick={addModel}
        disabled={selectedModels.length >= routableModels.length - 1}
        className="button-secondary disabled:cursor-not-allowed disabled:opacity-50"
      >
        <Plus className="h-4 w-4" />
        Add Fallback
      </button>
    </div>
  )
}
