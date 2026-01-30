import { Plus, Trash2 } from "lucide-react";
import { ModelInfo } from "../types";

interface FallbackModelsListProps {
  selectedModels: string[];
  availableModels: ModelInfo[];
  onChange: (models: string[]) => void;
}

export function FallbackModelsList({
  selectedModels,
  availableModels,
  onChange,
}: FallbackModelsListProps) {
  const addModel = () => {
    const available = availableModels.filter((m) => !selectedModels.includes(m.id));
    if (available.length > 0) {
      onChange([...selectedModels, available[0].id]);
    }
  };

  const removeModel = (index: number) => {
    onChange(selectedModels.filter((_, i) => i !== index));
  };

  const updateModel = (index: number, value: string) => {
    const updated = [...selectedModels];
    updated[index] = value;
    onChange(updated);
  };

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        Fallback Models (in order)
      </label>
      {selectedModels.length === 0 ? (
        <p className="text-xs text-slate-400 italic">No fallback models configured</p>
      ) : (
        <div className="space-y-2">
          {selectedModels.map((model, index) => (
            <div key={index} className="flex items-center gap-2">
              <select
                value={model}
                onChange={(e) => updateModel(index, e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <button
                onClick={() => removeModel(index)}
                className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/20 text-red-500"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        onClick={addModel}
        disabled={selectedModels.length >= availableModels.length - 1}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/20 rounded-lg transition-colors disabled:opacity-50"
      >
        <Plus className="h-3.5 w-3.5" />
        Add Fallback
      </button>
    </div>
  );
}
