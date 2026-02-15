import { cn } from "@/lib/utils";
import type { QualityPreference } from "./tier-matrix-grid";

const PREFERENCE_CONFIG: Record<QualityPreference, { label: string; description: string }> = {
  economy: { label: "Economy", description: "Minimize cost - cheapest model per tier" },
  standard: { label: "Standard", description: "Balance quality and cost - best value" },
  advanced: { label: "Advanced", description: "Maximize quality - highest scoring models" },
};

interface MatrixHeaderProps {
  preference: QualityPreference;
  onPreferenceChange: (preference: QualityPreference) => void;
}

export function MatrixHeader({ preference, onPreferenceChange }: MatrixHeaderProps) {
  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
          Model Selection Matrix
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          See which model gets selected at each complexity level based on your quality preference
        </p>
      </div>
      <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-1">
        {(Object.entries(PREFERENCE_CONFIG) as [QualityPreference, { label: string; description: string }][]).map(
          ([key, config]) => (
            <button
              key={key}
              type="button"
              onClick={() => onPreferenceChange(key)}
              className={cn(
                "px-4 py-2 rounded-md text-sm font-medium transition-all",
                preference === key
                  ? "bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 shadow-sm"
                  : "text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200"
              )}
              title={config.description}
            >
              {config.label}
            </button>
          )
        )}
      </div>
    </div>
  );
}

export function getCostDescription(preference: QualityPreference): string {
  return PREFERENCE_CONFIG[preference].description;
}
