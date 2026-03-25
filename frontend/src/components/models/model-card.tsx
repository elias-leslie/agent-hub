"use client";

import { Brain, Camera, Eye, FileText, Headphones, Pencil, Zap, Clock, Gauge, Database } from "lucide-react";
import { cn } from "@/lib/utils";
import { PROVIDER_COLORS } from "@/components/settings/constants";
import { ModelRadar } from "./model-radar";
import type { ModelOption } from "@agent-hub/chat-ui";

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
      return "bg-green-500/10 text-green-400 border-green-500/20";
    case "medium":
      return "bg-amber-500/10 text-amber-400 border-amber-500/20";
    case "slow":
      return "bg-red-500/10 text-red-400 border-red-500/20";
    default:
      return "bg-slate-500/10 text-slate-400 border-slate-500/20";
  }
}

export function ModelCard({ model, isSelected, onSelect, onExpand }: ModelCardProps) {
  const costTier = getCostTier(model.cost.input_per_m);
  const providerColor = PROVIDER_COLORS[model.provider];
  const hasEnrichment = !!model.enrichment;

  return (
    <div
      className={cn(
        "group relative rounded-lg border bg-slate-900 overflow-hidden",
        "transition-all duration-200",
        isSelected
          ? "border-amber-500/40 shadow-lg shadow-amber-500/10 ring-2 ring-amber-500/20"
          : "border-slate-800 hover:border-slate-700 hover:shadow-md",
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
            <div className="flex items-center gap-1.5">
              <h3 className="text-base font-semibold text-slate-100 truncate">
                {model.name}
              </h3>
              {hasEnrichment && (
                <Database className="h-3 w-3 text-emerald-500 flex-shrink-0" />
              )}
            </div>
            <p className="text-xs text-slate-400 truncate mt-0.5">
              {model.alias}
              {model.family && (
                <span className="ml-1 text-slate-400">({model.family})</span>
              )}
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
            <div className="text-xs text-slate-400 mb-1">
              Composite Score
            </div>
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold text-slate-100">
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
                  ? "bg-green-500/10 text-green-400 border-green-500/20"
                  : "bg-slate-800 text-slate-300 border-slate-700",
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
        <div className="flex flex-wrap items-center gap-1.5 mb-3">
          {model.capabilities.has_vision && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-blue-500/10 text-amber-400 border border-blue-500/20"
              title="Vision"
            >
              <Eye className="h-2.5 w-2.5" />
              Vision
            </div>
          )}
          {model.capabilities.has_thinking && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-violet-500/10 text-violet-400 border border-violet-500/20"
              title="Extended Thinking"
            >
              <Brain className="h-2.5 w-2.5" />
              Thinking
            </div>
          )}
          {model.capabilities.can_generate_images && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/20"
              title="Image Generation"
            >
              <Camera className="h-2.5 w-2.5" />
              Image
            </div>
          )}
          {model.capabilities.supports_pdf && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-orange-500/10 text-orange-400 border border-orange-500/20"
              title="PDF Processing"
            >
              <FileText className="h-2.5 w-2.5" />
              PDF
            </div>
          )}
          {model.capabilities.supports_audio && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-teal-500/10 text-teal-400 border border-teal-500/20"
              title="Audio Input"
            >
              <Headphones className="h-2.5 w-2.5" />
              Audio
            </div>
          )}
          {model.capabilities.can_edit_images && (
            <div
              className="flex items-center gap-1 px-2 py-0.5 rounded-md text-[10px] bg-pink-500/10 text-pink-400 border border-pink-500/20"
              title="Image Editing"
            >
              <Pencil className="h-2.5 w-2.5" />
              Edit
            </div>
          )}
        </div>

        {/* Context Window & Timeout */}
        <div className="text-xs text-slate-400 border-t border-slate-800 pt-3 space-y-1.5">
          <div className="flex justify-between">
            <span>Context Window</span>
            <span className="font-mono font-medium text-slate-300">
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
                ? "bg-amber-500 text-slate-950 border-amber-400"
                : "bg-slate-800 text-slate-300 border-slate-700 hover:bg-slate-700",
            )}
          >
            {isSelected ? "Selected" : "Compare"}
          </button>
        )}
      </div>
    </div>
  );
}
