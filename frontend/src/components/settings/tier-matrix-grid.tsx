"use client";

import { useMemo, useState } from "react";
import { cn } from "@/lib/utils";
import { useModels, type ModelOption } from "@/components/chat/use-models";
import { PROVIDER_COLORS } from "./constants";

export type QualityPreference = "economy" | "standard" | "advanced";
export type ComplexityTier = 1 | 2 | 3 | 4;

interface TierMatrixGridProps {
  preference: QualityPreference;
  onPreferenceChange: (preference: QualityPreference) => void;
}

const MIN_COMPOSITE: Record<ComplexityTier, number> = {
  1: 40,
  2: 60,
  3: 72,
  4: 79,
};

const TIER_LABELS: Record<ComplexityTier, string> = {
  1: "Simple",
  2: "Medium",
  3: "Complex",
  4: "Expert",
};

const PREFERENCE_CONFIG: Record<
  QualityPreference,
  { label: string; description: string }
> = {
  economy: {
    label: "Economy",
    description: "Minimize cost - cheapest model per tier",
  },
  standard: {
    label: "Standard",
    description: "Balance quality and cost - best value",
  },
  advanced: {
    label: "Advanced",
    description: "Maximize quality - highest scoring models",
  },
};

function selectModelForCell(
  models: ModelOption[],
  provider: string,
  complexity: ComplexityTier,
  preference: QualityPreference
): ModelOption | null {
  const providerModels = models.filter((m) => m.provider === provider);
  const threshold = MIN_COMPOSITE[complexity];
  let candidates = providerModels.filter(
    (m) => m.scores.composite >= threshold
  );

  // Relax threshold if no candidates
  if (candidates.length === 0) {
    candidates = providerModels.filter(
      (m) => m.scores.composite >= threshold - 10
    );
  }
  if (candidates.length === 0) {
    candidates = providerModels;
  }
  if (candidates.length === 0) return null;

  switch (preference) {
    case "economy":
      return candidates.sort(
        (a, b) =>
          a.cost.input_per_m +
          a.cost.output_per_m -
          (b.cost.input_per_m + b.cost.output_per_m)
      )[0];
    case "standard": {
      return candidates.sort((a, b) => {
        const costA = a.cost.input_per_m + a.cost.output_per_m || 0.01;
        const costB = b.cost.input_per_m + b.cost.output_per_m || 0.01;
        return b.scores.composite / costB - a.scores.composite / costA;
      })[0];
    }
    case "advanced":
      return candidates.sort(
        (a, b) => b.scores.composite - a.scores.composite
      )[0];
  }
}

export function TierMatrixGrid({
  preference,
  onPreferenceChange,
}: TierMatrixGridProps) {
  const models = useModels();
  const [hoveredCell, setHoveredCell] = useState<string | null>(null);

  const providers = useMemo(() => {
    const providerSet = new Set(models.map((m) => m.provider));
    return Array.from(providerSet).sort();
  }, [models]);

  const tiers: ComplexityTier[] = [1, 2, 3, 4];

  const matrixData = useMemo(() => {
    const matrix: Record<string, Record<ComplexityTier, ModelOption | null>> =
      {};

    for (const provider of providers) {
      matrix[provider] = {} as Record<ComplexityTier, ModelOption | null>;
      for (const tier of tiers) {
        matrix[provider][tier] = selectModelForCell(
          models,
          provider,
          tier,
          preference
        );
      }
    }

    return matrix;
  }, [models, providers, tiers, preference]);

  const estimatedCost = useMemo(() => {
    const allModels = Object.values(matrixData).flatMap((tierMap) =>
      Object.values(tierMap).filter((m): m is ModelOption => m !== null)
    );
    if (allModels.length === 0) return 0;
    const avgCost =
      allModels.reduce(
        (sum, m) => sum + m.cost.input_per_m + m.cost.output_per_m,
        0
      ) / allModels.length;
    return avgCost;
  }, [matrixData]);

  const getCostColor = (cost: number): string => {
    if (cost < 1) return "text-green-600 dark:text-green-400";
    if (cost < 5) return "text-amber-600 dark:text-amber-400";
    return "text-red-600 dark:text-red-400";
  };

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-6">
      <div className="space-y-6">
        {/* Header with Preference Toggle */}
        <div className="space-y-4">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Model Selection Matrix
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
              See which model gets selected at each complexity level based on
              your quality preference
            </p>
          </div>

          {/* Preference Segmented Control */}
          <div className="inline-flex rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800 p-1">
            {(
              Object.entries(PREFERENCE_CONFIG) as [
                QualityPreference,
                { label: string; description: string }
              ][]
            ).map(([key, config]) => (
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
            ))}
          </div>
        </div>

        {/* Grid */}
        <div className="overflow-x-auto">
          <div className="inline-block min-w-full align-middle">
            <table className="w-full border-collapse">
              {/* Header Row */}
              <thead>
                <tr>
                  <th className="p-3 text-left text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700">
                    Complexity
                  </th>
                  {providers.map((provider) => (
                    <th
                      key={provider}
                      className="p-3 text-center text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wider border-b border-slate-200 dark:border-slate-700"
                    >
                      <div className="flex items-center justify-center gap-1.5">
                        <div
                          className={cn(
                            "w-2 h-2 rounded-full",
                            PROVIDER_COLORS[provider]?.dot || "bg-slate-400"
                          )}
                        />
                        <span className="capitalize">{provider}</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>

              {/* Body */}
              <tbody>
                {tiers.map((tier) => (
                  <tr key={tier}>
                    {/* Tier Label */}
                    <td className="p-3 text-sm font-medium text-slate-700 dark:text-slate-300 border-b border-slate-200 dark:border-slate-700">
                      <div className="flex items-center gap-2">
                        <span className="inline-flex items-center px-2 py-1 rounded-md text-xs font-medium font-mono tabular-nums border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
                          T{tier}
                        </span>
                        <span>{TIER_LABELS[tier]}</span>
                      </div>
                    </td>

                    {/* Model Cells */}
                    {providers.map((provider) => {
                      const model = matrixData[provider]?.[tier];
                      const cellKey = `${provider}-${tier}`;
                      const isHovered = hoveredCell === cellKey;

                      return (
                        <td
                          key={provider}
                          className="p-2 border-b border-slate-200 dark:border-slate-700 relative"
                          onMouseEnter={() => setHoveredCell(cellKey)}
                          onMouseLeave={() => setHoveredCell(null)}
                        >
                          {model ? (
                            <>
                              <div
                                className={cn(
                                  "relative rounded-lg p-3 transition-all duration-200 cursor-pointer",
                                  "border",
                                  PROVIDER_COLORS[provider]?.bg ||
                                    "border-slate-200",
                                  isHovered &&
                                    "shadow-md scale-105 ring-2 ring-offset-2 dark:ring-offset-slate-900",
                                  provider === "claude" &&
                                    "bg-amber-50/50 dark:bg-amber-950/20 hover:bg-amber-50 dark:hover:bg-amber-950/30",
                                  provider === "gemini" &&
                                    "bg-blue-50/50 dark:bg-blue-950/20 hover:bg-blue-50 dark:hover:bg-blue-950/30",
                                  provider === "openai" &&
                                    "bg-green-50/50 dark:bg-green-950/20 hover:bg-green-50 dark:hover:bg-green-950/30",
                                  provider === "openrouter" &&
                                    "bg-purple-50/50 dark:bg-purple-950/20 hover:bg-purple-50 dark:hover:bg-purple-950/30",
                                  provider === "xai" &&
                                    "bg-red-50/50 dark:bg-red-950/20 hover:bg-red-50 dark:hover:bg-red-950/30",
                                  provider === "zhipu" &&
                                    "bg-teal-50/50 dark:bg-teal-950/20 hover:bg-teal-50 dark:hover:bg-teal-950/30",
                                  provider === "minimax" &&
                                    "bg-orange-50/50 dark:bg-orange-950/20 hover:bg-orange-50 dark:hover:bg-orange-950/30",
                                  isHovered &&
                                    provider === "claude" &&
                                    "ring-amber-500/50",
                                  isHovered &&
                                    provider === "gemini" &&
                                    "ring-blue-500/50",
                                  isHovered &&
                                    provider === "openai" &&
                                    "ring-green-500/50",
                                  isHovered &&
                                    provider === "openrouter" &&
                                    "ring-purple-500/50",
                                  isHovered &&
                                    provider === "xai" &&
                                    "ring-red-500/50",
                                  isHovered &&
                                    provider === "zhipu" &&
                                    "ring-teal-500/50",
                                  isHovered &&
                                    provider === "minimax" &&
                                    "ring-orange-500/50"
                                )}
                              >
                                <div className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
                                  {model.alias}
                                </div>
                                <div className="flex items-center gap-1.5 mt-1">
                                  <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium font-mono tabular-nums bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
                                    {model.scores.composite}
                                  </span>
                                </div>
                              </div>

                              {/* Hover Tooltip */}
                              {isHovered && (
                                <div className="absolute z-50 bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-slate-900 dark:bg-slate-800 text-white rounded-lg shadow-xl border border-slate-700 min-w-[200px]">
                                  <div className="space-y-1">
                                    <p className="font-semibold text-sm">
                                      {model.name}
                                    </p>
                                    <div className="text-xs space-y-0.5 text-slate-300">
                                      <p>
                                        Composite Score:{" "}
                                        <span className="font-mono text-white">
                                          {model.scores.composite}/100
                                        </span>
                                      </p>
                                      <p>
                                        Cost:{" "}
                                        <span className="font-mono text-white">
                                          $
                                          {(
                                            model.cost.input_per_m +
                                            model.cost.output_per_m
                                          ).toFixed(2)}
                                        </span>
                                        /1M tokens
                                      </p>
                                      <p>
                                        Speed:{" "}
                                        <span className="capitalize text-white">
                                          {model.speed_tier}
                                        </span>
                                      </p>
                                    </div>
                                  </div>
                                  {/* Arrow */}
                                  <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-px">
                                    <div className="border-8 border-transparent border-t-slate-900 dark:border-t-slate-800" />
                                  </div>
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="p-3 text-center text-xs text-slate-400 dark:text-slate-600">
                              —
                            </div>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Cost Bar */}
        <div className="flex items-center justify-between p-4 rounded-lg bg-slate-50 dark:bg-slate-800/50 border border-slate-200 dark:border-slate-700">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Estimated avg. cost per 1M tokens:
            </span>
            <span
              className={cn(
                "text-lg font-bold font-mono tabular-nums",
                getCostColor(estimatedCost)
              )}
            >
              ${estimatedCost.toFixed(2)}
            </span>
          </div>
          <div className="text-xs text-slate-500 dark:text-slate-400">
            {PREFERENCE_CONFIG[preference].description}
          </div>
        </div>
      </div>
    </div>
  );
}
