import { ModelInfo } from "../types";

interface ModelSelectProps {
  value: string | null;
  onChange: (value: string | null) => void;
  label: string;
  models: ModelInfo[];
  allowNull?: boolean;
}

export function ModelSelect({
  value,
  onChange,
  label,
  models,
  allowNull = false,
}: ModelSelectProps) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
      >
        {allowNull && <option value="">None</option>}
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.name}
          </option>
        ))}
      </select>
    </div>
  );
}
