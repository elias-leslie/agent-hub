import { cn } from "@/lib/utils";
import type { ModelOption } from "@/components/chat/use-models";
import { PROVIDER_COLORS } from "./constants";

interface MatrixCellProps {
  model: ModelOption | null;
  provider: string;
  isHovered: boolean;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
}

function getCellBackgroundClass(provider: string, isHovered: boolean): string {
  const baseClasses = "rounded-lg p-3 transition-all duration-200 cursor-pointer border";
  const hoverClass = isHovered ? "shadow-md scale-105 ring-2 ring-offset-2 dark:ring-offset-slate-900" : "";

  const providerStyles: Record<string, { bg: string; ring: string }> = {
    claude: { bg: "bg-amber-50/50 dark:bg-amber-950/20 hover:bg-amber-50 dark:hover:bg-amber-950/30", ring: "ring-amber-500/50" },
    gemini: { bg: "bg-blue-50/50 dark:bg-blue-950/20 hover:bg-blue-50 dark:hover:bg-blue-950/30", ring: "ring-blue-500/50" },
    openai: { bg: "bg-green-50/50 dark:bg-green-950/20 hover:bg-green-50 dark:hover:bg-green-950/30", ring: "ring-green-500/50" },
    openrouter: { bg: "bg-purple-50/50 dark:bg-purple-950/20 hover:bg-purple-50 dark:hover:bg-purple-950/30", ring: "ring-purple-500/50" },
    xai: { bg: "bg-red-50/50 dark:bg-red-950/20 hover:bg-red-50 dark:hover:bg-red-950/30", ring: "ring-red-500/50" },
    zhipu: { bg: "bg-teal-50/50 dark:bg-teal-950/20 hover:bg-teal-50 dark:hover:bg-teal-950/30", ring: "ring-teal-500/50" },
    minimax: { bg: "bg-orange-50/50 dark:bg-orange-950/20 hover:bg-orange-50 dark:hover:bg-orange-950/30", ring: "ring-orange-500/50" },
  };

  const style = providerStyles[provider] || { bg: "", ring: "" };
  const borderClass = PROVIDER_COLORS[provider]?.bg || "border-slate-200";

  return cn(
    baseClasses,
    borderClass,
    style.bg,
    hoverClass,
    isHovered && style.ring
  );
}

function HoverTooltip({ model }: { model: ModelOption }) {
  return (
    <div className="absolute z-50 bottom-full left-1/2 transform -translate-x-1/2 mb-2 px-3 py-2 bg-slate-900 dark:bg-slate-800 text-white rounded-lg shadow-xl border border-slate-700 min-w-[200px]">
      <div className="space-y-1">
        <p className="font-semibold text-sm">{model.name}</p>
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
              ${(model.cost.input_per_m + model.cost.output_per_m).toFixed(2)}
            </span>
            /1M tokens
          </p>
          <p>
            Speed:{" "}
            <span className="capitalize text-white">{model.speed_tier}</span>
          </p>
        </div>
      </div>
      <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-px">
        <div className="border-8 border-transparent border-t-slate-900 dark:border-t-slate-800" />
      </div>
    </div>
  );
}

export function MatrixCell({ model, provider, isHovered, onMouseEnter, onMouseLeave }: MatrixCellProps) {
  if (!model) {
    return (
      <td className="p-2 border-b border-slate-200 dark:border-slate-700">
        <div className="p-3 text-center text-xs text-slate-400 dark:text-slate-600">
          —
        </div>
      </td>
    );
  }

  return (
    <td
      className="p-2 border-b border-slate-200 dark:border-slate-700 relative"
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className={getCellBackgroundClass(provider, isHovered)}>
        <div className="text-sm font-medium text-slate-900 dark:text-slate-100 truncate">
          {model.alias}
        </div>
        <div className="flex items-center gap-1.5 mt-1">
          <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium font-mono tabular-nums bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-300">
            {model.scores.composite}
          </span>
        </div>
      </div>
      {isHovered && <HoverTooltip model={model} />}
    </td>
  );
}
