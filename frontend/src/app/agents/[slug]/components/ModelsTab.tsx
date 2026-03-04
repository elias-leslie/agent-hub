"use client";

import { useEffect, useState } from "react";
import { Clock } from "lucide-react";
import { Agent, ModelInfo } from "../types";
import { ModelSelect } from "./ModelSelect";
import { FallbackModelsList } from "./FallbackModelsList";

interface ModelsTabProps {
  formData: Partial<Agent>;
  availableModels: ModelInfo[];
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

function TimeoutHint({ modelId }: { modelId: string | undefined }) {
  const [hint, setHint] = useState<number | null>(null);

  useEffect(() => {
    if (!modelId) { setHint(null); return; }
    (async () => {
      try {
        const { getModels } = await import("@/lib/models");
        const models = await getModels();
        const model = models.find((m) => m.id === modelId);
        setHint(model?.timeout_hint_seconds ?? null);
      } catch {
        setHint(null);
      }
    })();
  }, [modelId]);

  if (hint === null) return null;

  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-slate-700/50 text-[10px] text-slate-400 ml-2">
      <Clock className="h-2.5 w-2.5" />
      Timeout hint: {hint}s
    </span>
  );
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
        <div>
          <ModelSelect
            label="Primary Model"
            value={formData.primary_model_id ?? null}
            onChange={(v) => updateField("primary_model_id", v ?? "")}
            models={availableModels}
          />
          <TimeoutHint modelId={formData.primary_model_id} />
        </div>

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

        <ModelSelect
          label="Premium Model (for tier=advanced requests)"
          value={formData.premium_model_id ?? null}
          onChange={(v) => updateField("premium_model_id", v)}
          models={availableModels}
          allowNull
        />
      </div>
    </div>
  );
}
