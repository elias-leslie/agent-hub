import { X, Check, Minus, Brain, Camera, Eye, FileText, Headphones, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import { PROVIDER_COLORS } from "@/components/settings/constants";
import { formatModelPricing } from "@/lib/model-pricing";
import type { ModelOption, ModelScores } from "@agent-hub/chat-ui";

const SCORE_CATEGORIES: Array<keyof Omit<ModelScores, "composite">> = [
  "coding",
  "reasoning",
  "planning",
  "tool_use",
  "instruction",
  "design",
];

interface SectionProps {
  models: ModelOption[];
}

export function ScoreBreakdown({ models }: SectionProps) {
  return (
    <div className="space-y-6">
      <h3 className="text-sm font-semibold text-slate-100">
        Score Breakdown
      </h3>
      {SCORE_CATEGORIES.map((category) => (
        <div key={category}>
          <div className="text-xs font-medium text-slate-400 mb-2 capitalize">
            {category.replace("_", " ")}
          </div>
          <div className="space-y-2">
            {models.map((model) => {
              const score = model.scores[category];
              const providerColor = PROVIDER_COLORS[model.provider];
              return (
                <div key={model.id} className="flex items-center gap-3">
                  <div className="w-32 flex-shrink-0">
                    <div className="flex items-center gap-2">
                      <div className={cn("w-2 h-2 rounded-full", providerColor.dot)} />
                      <span className="text-xs text-slate-300 truncate">
                        {model.name}
                      </span>
                    </div>
                  </div>
                  <div className="flex-1 h-6 bg-slate-800 rounded-full overflow-hidden">
                    <div
                      className={cn(
                        "h-full rounded-full transition-all duration-500",
                        providerColor.dot.replace("bg-", "bg-gradient-to-r from-"),
                      )}
                      style={{ width: `${score}%` }}
                    />
                  </div>
                  <span className="text-xs font-mono font-semibold text-slate-300 w-10 text-right">
                    {score}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      ))}
    </div>
  );
}

export function CompositeScore({ models }: SectionProps) {
  return (
    <div className="bg-gradient-to-br from-amber-950/20 to-orange-950/20 rounded-lg p-6 border border-amber-900/30">
      <h3 className="text-sm font-semibold text-slate-100 mb-4">
        Composite Score
      </h3>
      <div className="grid grid-cols-1 gap-3">
        {models.map((model) => {
          const providerColor = PROVIDER_COLORS[model.provider];
          return (
            <div
              key={model.id}
              className="flex items-center justify-between bg-slate-900 rounded-lg p-4 border border-slate-800"
            >
              <div className="flex items-center gap-3">
                <div className={cn("w-3 h-3 rounded-full", providerColor.dot)} />
                <span className="text-sm font-medium text-slate-100">
                  {model.name}
                </span>
              </div>
              <div className="text-2xl font-bold text-slate-100">
                {model.scores.composite}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CostComparison({ models }: SectionProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-100">
        Cost Comparison
      </h3>
      <div className="grid grid-cols-1 gap-3">
        {models.map((model) => {
          const providerColor = PROVIDER_COLORS[model.provider];
          const pricing = formatModelPricing(model.cost);
          return (
            <div
              key={model.id}
              className="flex items-center justify-between bg-slate-800/50 rounded-lg p-4 border border-slate-700"
            >
              <div className="flex items-center gap-3">
                <div className={cn("w-3 h-3 rounded-full", providerColor.dot)} />
                <span className="text-sm font-medium text-slate-100">
                  {model.name}
                </span>
              </div>
              <div className="flex items-center gap-4">
                <div className="text-right">
                  <div className="text-xs uppercase tracking-[0.16em] text-slate-500">Pricing</div>
                  <div className="text-sm font-mono font-semibold text-slate-100">
                    {pricing.primary}
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {pricing.secondary}
                  </div>
                </div>
                <div
                  className={cn(
                    "rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]",
                    model.cost.source === "enrichment"
                      ? "border-emerald-500/20 bg-emerald-500/10 text-emerald-200"
                      : "border-slate-700 bg-slate-800 text-slate-300",
                  )}
                >
                  {pricing.source}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function ContextWindow({ models }: SectionProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-100">
        Context Window
      </h3>
      <div className="grid grid-cols-1 gap-3">
        {models.map((model) => {
          const providerColor = PROVIDER_COLORS[model.provider];
          return (
            <div
              key={model.id}
              className="flex items-center justify-between bg-slate-800/50 rounded-lg p-4 border border-slate-700"
            >
              <div className="flex items-center gap-3">
                <div className={cn("w-3 h-3 rounded-full", providerColor.dot)} />
                <span className="text-sm font-medium text-slate-100">
                  {model.name}
                </span>
              </div>
              <span className="text-sm font-mono font-semibold text-slate-100">
                {(model.context_window / 1000).toFixed(0)}K tokens
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export function CapabilitiesMatrix({ models }: SectionProps) {
  return (
    <div className="space-y-4">
      <h3 className="text-sm font-semibold text-slate-100">
        Capabilities
      </h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-800">
              <th className="text-left py-3 px-4 text-xs font-medium text-slate-400">
                Model
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <Eye className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">Vision</div>
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <Brain className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">Think</div>
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <Camera className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">Image</div>
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <FileText className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">PDF</div>
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <Headphones className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">Audio</div>
              </th>
              <th className="text-center py-3 px-2 text-xs font-medium text-slate-400">
                <Pencil className="h-3.5 w-3.5 mx-auto" />
                <div className="mt-1">Edit</div>
              </th>
            </tr>
          </thead>
          <tbody>
            {models.map((model) => {
              const providerColor = PROVIDER_COLORS[model.provider];
              return (
                <tr
                  key={model.id}
                  className="border-b border-slate-800/50"
                >
                  <td className="py-3 px-4">
                    <div className="flex items-center gap-2">
                      <div className={cn("w-2 h-2 rounded-full", providerColor.dot)} />
                      <span className="font-medium text-slate-100">
                        {model.name}
                      </span>
                    </div>
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.has_vision ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.has_thinking ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.can_generate_images ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.supports_pdf ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.supports_audio ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                  <td className="text-center py-3 px-2">
                    {model.capabilities.can_edit_images ? (
                      <Check className="h-3.5 w-3.5 text-green-500 mx-auto" />
                    ) : (
                      <Minus className="h-3.5 w-3.5 text-slate-600 mx-auto" />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

interface RemoveButtonsProps {
  models: ModelOption[];
  onRemoveModel: (modelId: string) => void;
}

export function RemoveButtons({ models, onRemoveModel }: RemoveButtonsProps) {
  return (
    <div className="flex flex-wrap gap-2">
      {models.map((model) => {
        const providerColor = PROVIDER_COLORS[model.provider];
        return (
          <button
            key={model.id}
            type="button"
            onClick={() => onRemoveModel(model.id)}
            className="flex items-center gap-2 px-3 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 transition-colors"
          >
            <div className={cn("w-2 h-2 rounded-full", providerColor.dot)} />
            <span className="text-xs font-medium text-slate-100">
              {model.name}
            </span>
            <X className="h-3 w-3 text-slate-400" />
          </button>
        );
      })}
    </div>
  );
}
