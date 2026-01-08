"use client";

import { useState } from "react";
import { Cpu, Server, ChevronRight, CheckCircle, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

interface Model {
  id: string;
  name: string;
  provider: "claude" | "gemini";
  available: boolean;
  recommended?: boolean;
  reason?: string;
}

interface ModelSwitcherProps {
  currentModel: string;
  models: Model[];
  onSwitch: (modelId: string) => void;
  errorType?: "rate_limit" | "provider_down" | "context_overflow";
  className?: string;
}

/**
 * ModelSwitcher - Quick model switching for error recovery.
 *
 * Design: Compact list with availability status and recommendations.
 */
export function ModelSwitcher({
  currentModel,
  models,
  onSwitch,
  errorType,
  className,
}: ModelSwitcherProps) {
  const [selectedModel, setSelectedModel] = useState<string | null>(null);

  const availableModels = models.filter(
    (m) => m.id !== currentModel && m.available
  );
  const unavailableModels = models.filter(
    (m) => m.id !== currentModel && !m.available
  );

  const getRecommendation = (model: Model): string | undefined => {
    if (model.recommended) return model.reason;

    if (errorType === "context_overflow" && model.name.includes("Opus")) {
      return "Larger context window";
    }
    if (errorType === "rate_limit") {
      const current = models.find((m) => m.id === currentModel);
      if (current?.provider !== model.provider) {
        return "Different provider";
      }
    }
    return undefined;
  };

  return (
    <div
      className={cn(
        "rounded-xl border bg-white dark:bg-slate-900",
        "border-slate-200 dark:border-slate-800",
        className
      )}
    >
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-800">
        <h3 className="font-semibold text-slate-900 dark:text-slate-100">
          Switch Model
        </h3>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-0.5">
          Try a different model to continue
        </p>
      </div>

      <div className="p-2">
        {/* Available models */}
        {availableModels.map((model) => {
          const recommendation = getRecommendation(model);
          const Icon = model.provider === "claude" ? Cpu : Server;
          const isSelected = selectedModel === model.id;

          return (
            <button
              key={model.id}
              onClick={() => {
                setSelectedModel(model.id);
                onSwitch(model.id);
              }}
              className={cn(
                "w-full flex items-center gap-3 p-3 rounded-lg text-left transition-all",
                "hover:bg-slate-50 dark:hover:bg-slate-800/50",
                isSelected && "bg-slate-100 dark:bg-slate-800"
              )}
            >
              <div
                className={cn(
                  "p-2 rounded-lg",
                  model.provider === "claude"
                    ? "bg-orange-100 dark:bg-orange-900/30"
                    : "bg-blue-100 dark:bg-blue-900/30"
                )}
              >
                <Icon
                  className={cn(
                    "h-4 w-4",
                    model.provider === "claude"
                      ? "text-orange-600 dark:text-orange-400"
                      : "text-blue-600 dark:text-blue-400"
                  )}
                />
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <span className="font-medium text-slate-900 dark:text-slate-100">
                    {model.name}
                  </span>
                  {model.recommended && (
                    <span className="flex items-center gap-0.5 text-xs px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-400">
                      <Zap className="h-3 w-3" />
                      Recommended
                    </span>
                  )}
                </div>
                {recommendation && (
                  <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                    {recommendation}
                  </p>
                )}
              </div>

              {isSelected ? (
                <CheckCircle className="h-5 w-5 text-emerald-500" />
              ) : (
                <ChevronRight className="h-5 w-5 text-slate-300 dark:text-slate-600" />
              )}
            </button>
          );
        })}

        {/* Unavailable models */}
        {unavailableModels.length > 0 && (
          <>
            <div className="my-2 px-3">
              <div className="h-px bg-slate-200 dark:bg-slate-700" />
            </div>
            <p className="px-3 py-1 text-xs text-slate-400 dark:text-slate-500">
              Unavailable
            </p>
            {unavailableModels.map((model) => {
              const Icon = model.provider === "claude" ? Cpu : Server;

              return (
                <div
                  key={model.id}
                  className="flex items-center gap-3 p-3 opacity-50"
                >
                  <div className="p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
                    <Icon className="h-4 w-4 text-slate-400 dark:text-slate-500" />
                  </div>
                  <div className="flex-1 min-w-0">
                    <span className="font-medium text-slate-500 dark:text-slate-400">
                      {model.name}
                    </span>
                    <p className="text-xs text-slate-400 dark:text-slate-500 mt-0.5">
                      {model.reason || "Currently unavailable"}
                    </p>
                  </div>
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}

interface QuickModelSwitchProps {
  currentModel: string;
  alternativeModel: Model;
  onSwitch: () => void;
  className?: string;
}

/**
 * QuickModelSwitch - Inline one-click model switch suggestion.
 */
export function QuickModelSwitch({
  currentModel,
  alternativeModel,
  onSwitch,
  className,
}: QuickModelSwitchProps) {
  const Icon = alternativeModel.provider === "claude" ? Cpu : Server;

  return (
    <button
      onClick={onSwitch}
      className={cn(
        "flex items-center gap-2 px-3 py-2 rounded-lg text-sm",
        "bg-slate-100 dark:bg-slate-800",
        "hover:bg-slate-200 dark:hover:bg-slate-700",
        "transition-colors",
        className
      )}
    >
      <Icon
        className={cn(
          "h-4 w-4",
          alternativeModel.provider === "claude"
            ? "text-orange-500 dark:text-orange-400"
            : "text-blue-500 dark:text-blue-400"
        )}
      />
      <span className="text-slate-700 dark:text-slate-300">
        Try <span className="font-medium">{alternativeModel.name}</span> instead
      </span>
      <ChevronRight className="h-4 w-4 text-slate-400" />
    </button>
  );
}
