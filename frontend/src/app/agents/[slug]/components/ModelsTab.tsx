import { Agent, ModelInfo } from "../types";
import { ModelSelect } from "./ModelSelect";
import { FallbackModelsList } from "./FallbackModelsList";

interface ModelsTabProps {
  formData: Partial<Agent>;
  availableModels: ModelInfo[];
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export function ModelsTab({ formData, availableModels, updateField }: ModelsTabProps) {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
          Model Configuration
        </h2>
      </div>

      <div className="space-y-6">
        <ModelSelect
          label="Primary Model"
          value={formData.primary_model_id ?? null}
          onChange={(v) => updateField("primary_model_id", v ?? "")}
          models={availableModels}
        />

        <FallbackModelsList
          selectedModels={formData.fallback_models ?? []}
          availableModels={availableModels}
          onChange={(models) => updateField("fallback_models", models)}
        />

        <ModelSelect
          label="Escalation Model (for complex tasks)"
          value={formData.escalation_model_id ?? null}
          onChange={(v) => updateField("escalation_model_id", v)}
          models={availableModels}
          allowNull
        />
      </div>
    </div>
  );
}
