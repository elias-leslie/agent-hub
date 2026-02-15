"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useModels, type ModelOption } from "@/components/chat/use-models";
import { selectModelForCell } from "./tier-matrix-selection";
import { MatrixHeader, getCostDescription } from "./tier-matrix-header";
import { MatrixTable } from "./tier-matrix-table";

export type QualityPreference = "economy" | "standard" | "advanced";
export type ComplexityTier = 1 | 2 | 3 | 4;

interface TierMatrixGridProps {
  preference: QualityPreference;
  onPreferenceChange: (preference: QualityPreference) => void;
}

function getCostColor(cost: number): string {
  if (cost < 1) return "text-green-600 dark:text-green-400";
  if (cost < 5) return "text-amber-600 dark:text-amber-400";
  return "text-red-600 dark:text-red-400";
}

export function TierMatrixGrid({ preference, onPreferenceChange }: TierMatrixGridProps) {
  const models = useModels();
  const [hoveredCell, setHoveredCell] = useState<string | null>(null);

  const providers = useMemo(() => {
    const providerSet = new Set(models.map((m) => m.provider));
    return Array.from(providerSet).sort();
  }, [models]);

  const tiers: ComplexityTier[] = [1, 2, 3, 4];

  const matrixData = useMemo(() => {
    const matrix: Record<string, Record<ComplexityTier, ModelOption | null>> = {};
    for (const provider of providers) {
      matrix[provider] = {} as Record<ComplexityTier, ModelOption | null>;
      for (const tier of tiers) {
        matrix[provider][tier] = selectModelForCell(models, provider, tier, preference);
      }
    }
    return matrix;
  }, [models, providers, tiers, preference]);

  const estimatedCost = useMemo(() => {
    const allModels = Object.values(matrixData).flatMap((tierMap) =>
      Object.values(tierMap).filter((m): m is ModelOption => m !== null)
    );
    if (allModels.length === 0) return 0;
    return allModels.reduce((sum, m) => sum + m.cost.input_per_m + m.cost.output_per_m, 0) / allModels.length;
  }, [matrixData]);

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6">
      <div className="space-y-6">
        <MatrixHeader preference={preference} onPreferenceChange={onPreferenceChange} />
        <MatrixTable
          providers={providers}
          tiers={tiers}
          matrixData={matrixData}
          hoveredCell={hoveredCell}
          onCellHover={setHoveredCell}
        />
        <div className="flex items-center justify-between p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Estimated avg. cost per 1M tokens:
            </span>
            <span className={cn("text-lg font-bold font-mono tabular-nums", getCostColor(estimatedCost))}>
              ${estimatedCost.toFixed(2)}
            </span>
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400">{getCostDescription(preference)}</div>
        </div>
      </div>
    </div>
  );
}
