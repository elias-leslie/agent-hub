"use client";

import { Camera, Eye, Pencil, Zap, Clock, Gauge } from "lucide-react";
import { cn } from "@/lib/utils";
import { PROVIDER_COLORS } from "@/components/settings/constants";
import { ModelRadar } from "./model-radar";
import type { ModelOption } from "@/components/chat/use-models";

interface ModelCardProps {
  model: ModelOption;
  isSelected?: boolean;
  onSelect?: (model: ModelOption) => void;
  onExpand?: (model: ModelOption) => void;
}

function getCostTier(inputCostPerM: number): string {
  if (inputCostPerM === 0) return "Free";
  if (inputCostPerM < 0.5) return "$";
  if (inputCostPerM < 3) return "$$";
  return "$$$";
}

function getSpeedBadgeColor(tier: string): string {
  switch (tier) {
    case "fast":
      return "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20";
    case "medium":
      return "bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20";
    case "slow":
      return "bg-red-500/10 text-red-600 dark:text-red-400 border-red-500/20";
    default:
      return "bg-slate-500/10 text-slate-600 dark:text-slate-400 border-slate-500/20";
  }
}

export function ModelCard({ model, isSelected, onSelect, onExpand }: ModelCardProps) {
  const costTier = getCostTier(model.cost.input_per_m);
  const providerColor = PROVIDER_COLORS[model.provider];

  return (
    <div
      className={cn(
        "group relative rounded-lg border bg-white dark:bg-slate-900 overflow-hidden",
        "transition-all duration-200",
        isSelected
          ? "border-amber-500/40 shadow-lg shadow-amber-500/10 ring-2 ring-amber-500/20"
          : "border-slate-200 dark:border-slate-800 hover:border-slate-300 dark:hover:border-slate-700 hover:shadow-md",
      )}
      onClick={() => onExpand?.(model)}
    >
      {/* Provider accent */}
      <div
        className={cn(
          "absolute top-0 left-0 right-0 h-1",
          providerColor.dot.replace("bg-", "bg-gradient-to-r from-"),
        )}
      />

      <div className="p-5">
        {/* Header */}
        <div className="flex items-start justify-between mb-3">
          <div className="flex-1 min-w-0">
            <h3 className="text-base font-semibold text-slate-900 dark:text-slate-100 truncate">
              {model.name}
            </h3>
            <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
              {model.alias}
            </p>
          </div>

          {/* Provider badge */}
          <div className={cn(
            "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium border ml-2",
            providerColor.dot.replace("bg-", "text-"),
            providerColor.bg,
          )}>
            <div className={cn("w-1.5 h-1.5 rounded-full", providerColor.dot)} />
            <span className="capitalize">{model.provider}</span>
          </div>
        </div>

        {/* Composite Score */}
        <div className="flex items-center gap-2 mb-4">
          <div className="flex-1">
            <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">
              Composite Score
            </div>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold text-slate-900 dark:text-slate-100">
                {model.scores.composite}
              </span>
              <span className="text-xs text-slate-400">/100</span>
            </div>
          </div>

          {/* Cost & Speed */}
          <div className="flex flex-col gap-1.5">
            <div
              className={cn(
                "px-2 py-1 rounded text-xs font-semibold text-center border",
                costTier === "Free"
                  ? "bg-green-500/10 text-green-600 dark:text-green-400 border-green-500/20"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700",
              )}
            >
              {costTier}
            </div>
            <div
              className={cn(
                "px-2 py-1 rounded text-xs font-medium text-center border",
                getSpeedBadgeColor(model.speed_tier),
              )}
            >
              {model.speed_tier === "fast" && <Zap className="inline h-3 w-3 mr-0.5" />}
              {model.speed_tier === "medium" && <Gauge className="inline h-3 w-3 mr-0.5" />}
              {model.speed_tier === "slow" && <Clock className="inline h-3 w-3 mr-0.5" />}
              {model.speed_tier}
            </div>
          </div>
        </div>

        {/* Radar Chart */}
        <div className="mb-4 -mx-2">
          <ModelRadar models={[model]} size="sm" />
        </div>

        {/* Capabilities */}
        <div className="flex items-center gap-2 mb-3">
          {model.capabilities.has_vision && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-blue-500/10 text-blue-600 dark:text-blue-400 border border-blue-500/20"
              title="Vision"
            >
              <Eye className="h-3 w-3" />
              <span>Vision</span>
            </div>
          )}
          {model.capabilities.can_generate_images && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-purple-500/10 text-purple-600 dark:text-purple-400 border border-purple-500/20"
              title="Image Generation"
            >
              <Camera className="h-3 w-3" />
              <span>Image Gen</span>
            </div>
          )}
          {model.capabilities.can_edit_images && (
            <div
              className="flex items-center gap-1 px-2 py-1 rounded-md text-xs bg-pink-500/10 text-pink-600 dark:text-pink-400 border border-pink-500/20"
              title="Image Editing"
            >
              <Pencil className="h-3 w-3" />
              <span>Edit</span>
            </div>
          )}
        </div>

        {/* Context Window */}
        <div className="text-xs text-slate-500 dark:text-slate-400 border-t border-slate-200 dark:border-slate-800 pt-3">
          <div className="flex justify-between">
            <span>Context Window</span>
            <span className="font-mono font-medium text-slate-700 dark:text-slate-300">
              {(model.context_window / 1000).toFixed(0)}K
            </span>
          </div>
        </div>

        {/* Compare button */}
        {onSelect && (
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onSelect(model);
            }}
            className={cn(
              "absolute top-3 right-3 opacity-0 group-hover:opacity-100 transition-opacity",
              "px-2 py-1 rounded-md text-xs font-medium border",
              isSelected
                ? "bg-amber-500 text-white border-amber-600"
                : "bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-700",
            )}
          >
            {isSelected ? "Selected" : "Compare"}
          </button>
        )}
      </div>
    </div>
  );
}
