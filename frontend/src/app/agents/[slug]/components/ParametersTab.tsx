import { Agent } from "../types";

interface ParametersTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export function ParametersTab({ formData, updateField }: ParametersTabProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
          Generation Parameters
        </h2>
      </div>

      <div className="space-y-6">
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Temperature
            </label>
            <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
              {(formData.temperature ?? 0.7).toFixed(2)}
            </span>
          </div>
          <input
            type="range"
            min="0"
            max="2"
            step="0.1"
            value={formData.temperature ?? 0.7}
            onChange={(e) =>
              updateField("temperature", parseFloat(e.target.value))
            }
            className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <div className="flex justify-between text-[10px] text-slate-400">
            <span>Precise (0)</span>
            <span>Balanced (1)</span>
            <span>Creative (2)</span>
          </div>
        </div>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Timeout (seconds)
            </label>
            <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
              {formData.timeout_seconds ?? "Model default"}
            </span>
          </div>
          <input
            type="number"
            min="1"
            max="600"
            placeholder="Use model default"
            value={formData.timeout_seconds ?? ""}
            onChange={(e) => {
              const val = e.target.value ? parseFloat(e.target.value) : undefined;
              updateField("timeout_seconds", val);
            }}
            className="w-full px-3 py-2 text-sm rounded-lg bg-slate-100 dark:bg-slate-800 border border-slate-300 dark:border-slate-600 text-slate-800 dark:text-slate-200 placeholder-slate-400"
          />
          <p className="text-[10px] text-slate-400">
            Override the model&apos;s default timeout. Leave empty to use the model&apos;s timeout hint (based on speed tier).
          </p>
        </div>
      </div>
    </div>
  );
}
