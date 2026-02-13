"use client";

import { Search, Camera, Eye, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";
import { PROVIDER_COLORS } from "@/components/settings/constants";

interface ModelFiltersProps {
  searchQuery: string;
  onSearchChange: (query: string) => void;
  selectedProviders: Set<string>;
  onProviderToggle: (provider: string) => void;
  capabilityFilters: {
    vision: boolean;
    imageGen: boolean;
    imageEdit: boolean;
  };
  onCapabilityToggle: (capability: "vision" | "imageGen" | "imageEdit") => void;
  sortBy: string;
  onSortChange: (sort: string) => void;
  groupByProvider: boolean;
  onGroupByProviderToggle: () => void;
}

const PROVIDERS = [
  { id: "claude", name: "Claude" },
  { id: "gemini", name: "Gemini" },
  { id: "openai", name: "OpenAI" },
  { id: "openrouter", name: "OpenRouter" },
  { id: "xai", name: "xAI" },
  { id: "zhipu", name: "Zhipu" },
  { id: "minimax", name: "MiniMax" },
];

const SORT_OPTIONS = [
  { value: "composite", label: "Composite Score" },
  { value: "coding", label: "Coding Score" },
  { value: "reasoning", label: "Reasoning Score" },
  { value: "cost-asc", label: "Cost (Low to High)" },
  { value: "cost-desc", label: "Cost (High to Low)" },
  { value: "name", label: "Name" },
];

export function ModelFilters({
  searchQuery,
  onSearchChange,
  selectedProviders,
  onProviderToggle,
  capabilityFilters,
  onCapabilityToggle,
  sortBy,
  onSortChange,
  groupByProvider,
  onGroupByProviderToggle,
}: ModelFiltersProps) {
  return (
    <div className="space-y-4">
      {/* Search & Sort */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search models by name or alias..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
          />
        </div>

        <select
          value={sortBy}
          onChange={(e) => onSortChange(e.target.value)}
          className="px-4 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {/* Provider Filters */}
      <div>
        <div className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
          Providers
        </div>
        <div className="flex flex-wrap gap-2">
          {PROVIDERS.map((provider) => {
            const isSelected = selectedProviders.has(provider.id);
            const providerColor = PROVIDER_COLORS[provider.id];
            return (
              <button
                key={provider.id}
                type="button"
                onClick={() => onProviderToggle(provider.id)}
                className={cn(
                  "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
                  isSelected
                    ? cn(
                        "border-current",
                        providerColor.dot.replace("bg-", "text-"),
                        providerColor.bg,
                      )
                    : "border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600",
                )}
              >
                <div
                  className={cn(
                    "w-2 h-2 rounded-full",
                    isSelected ? providerColor.dot : "bg-slate-300 dark:bg-slate-600",
                  )}
                />
                <span>{provider.name}</span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Capability Filters */}
      <div>
        <div className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-2">
          Capabilities
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => onCapabilityToggle("vision")}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
              capabilityFilters.vision
                ? "bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20"
                : "border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600",
            )}
          >
            <Eye className="h-3 w-3" />
            <span>Vision</span>
          </button>

          <button
            type="button"
            onClick={() => onCapabilityToggle("imageGen")}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
              capabilityFilters.imageGen
                ? "bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20"
                : "border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600",
            )}
          >
            <Camera className="h-3 w-3" />
            <span>Image Generation</span>
          </button>

          <button
            type="button"
            onClick={() => onCapabilityToggle("imageEdit")}
            className={cn(
              "flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all",
              capabilityFilters.imageEdit
                ? "bg-pink-500/10 text-pink-600 dark:text-pink-400 border-pink-500/20"
                : "border-slate-200 dark:border-slate-700 text-slate-500 dark:text-slate-400 hover:border-slate-300 dark:hover:border-slate-600",
            )}
          >
            <Pencil className="h-3 w-3" />
            <span>Image Editing</span>
          </button>
        </div>
      </div>

      {/* Group by Provider Toggle */}
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={groupByProvider}
            onChange={onGroupByProviderToggle}
            className="rounded border-slate-300 dark:border-slate-600 text-amber-500 focus:ring-amber-500"
          />
          <span className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Group by Provider
          </span>
        </label>
      </div>
    </div>
  );
}
