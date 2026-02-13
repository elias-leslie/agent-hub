"use client";

import { useState, useMemo } from "react";
import { Cpu, RefreshCw, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { useModels } from "@/components/chat/use-models";
import { ModelCard } from "@/components/models/model-card";
import { ModelFilters } from "@/components/models/model-filters";
import { ModelComparison } from "@/components/models/model-comparison";
import type { ModelOption } from "@/components/chat/use-models";

export default function ModelsPage() {
  const models = useModels();
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedProviders, setSelectedProviders] = useState<Set<string>>(
    new Set(["claude", "gemini", "openai", "openrouter", "xai", "zhipu", "minimax"]),
  );
  const [capabilityFilters, setCapabilityFilters] = useState({
    vision: false,
    imageGen: false,
    imageEdit: false,
  });
  const [sortBy, setSortBy] = useState("composite");
  const [groupByProvider, setGroupByProvider] = useState(false);
  const [selectedModels, setSelectedModels] = useState<ModelOption[]>([]);
  const [expandedModel, setExpandedModel] = useState<ModelOption | null>(null);

  const handleProviderToggle = (provider: string) => {
    setSelectedProviders((prev) => {
      const next = new Set(prev);
      if (next.has(provider)) {
        next.delete(provider);
      } else {
        next.add(provider);
      }
      return next;
    });
  };

  const handleCapabilityToggle = (capability: "vision" | "imageGen" | "imageEdit") => {
    setCapabilityFilters((prev) => ({
      ...prev,
      [capability]: !prev[capability],
    }));
  };

  const handleModelSelect = (model: ModelOption) => {
    setSelectedModels((prev) => {
      const isSelected = prev.some((m) => m.id === model.id);
      if (isSelected) {
        return prev.filter((m) => m.id !== model.id);
      }
      if (prev.length >= 3) {
        // Max 3 models for comparison
        return prev;
      }
      return [...prev, model];
    });
  };

  const handleRemoveModel = (modelId: string) => {
    setSelectedModels((prev) => prev.filter((m) => m.id !== modelId));
  };

  const filteredModels = useMemo(() => {
    let filtered = models;

    // Filter by search query
    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase();
      filtered = filtered.filter(
        (model) =>
          model.name.toLowerCase().includes(query) ||
          model.alias.toLowerCase().includes(query) ||
          model.hint.toLowerCase().includes(query),
      );
    }

    // Filter by provider
    filtered = filtered.filter((model) => selectedProviders.has(model.provider));

    // Filter by capabilities
    if (capabilityFilters.vision) {
      filtered = filtered.filter((model) => model.capabilities.has_vision);
    }
    if (capabilityFilters.imageGen) {
      filtered = filtered.filter((model) => model.capabilities.can_generate_images);
    }
    if (capabilityFilters.imageEdit) {
      filtered = filtered.filter((model) => model.capabilities.can_edit_images);
    }

    // Sort
    filtered = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "composite":
          return b.scores.composite - a.scores.composite;
        case "coding":
          return b.scores.coding - a.scores.coding;
        case "reasoning":
          return b.scores.reasoning - a.scores.reasoning;
        case "cost-asc":
          return a.cost.input_per_m - b.cost.input_per_m;
        case "cost-desc":
          return b.cost.input_per_m - a.cost.input_per_m;
        case "name":
          return a.name.localeCompare(b.name);
        default:
          return 0;
      }
    });

    return filtered;
  }, [models, searchQuery, selectedProviders, capabilityFilters, sortBy]);

  const groupedModels = useMemo(() => {
    if (!groupByProvider) return null;

    const groups: Record<string, ModelOption[]> = {};
    for (const model of filteredModels) {
      if (!groups[model.provider]) {
        groups[model.provider] = [];
      }
      groups[model.provider].push(model);
    }
    return groups;
  }, [filteredModels, groupByProvider]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Cpu className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  Models
                </h1>
              </div>
              <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-500 dark:text-slate-400">
                  {filteredModels.length} of {models.length} models
                </span>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              {selectedModels.length > 0 && (
                <button
                  type="button"
                  onClick={() => setSelectedModels([])}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold bg-amber-600 text-white hover:bg-amber-700 transition-colors"
                >
                  Compare {selectedModels.length} Model{selectedModels.length !== 1 ? "s" : ""}
                </button>
              )}
            </div>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-5">
        {/* Filters */}
        <div className="mb-6">
          <ModelFilters
            searchQuery={searchQuery}
            onSearchChange={setSearchQuery}
            selectedProviders={selectedProviders}
            onProviderToggle={handleProviderToggle}
            capabilityFilters={capabilityFilters}
            onCapabilityToggle={handleCapabilityToggle}
            sortBy={sortBy}
            onSortChange={setSortBy}
            groupByProvider={groupByProvider}
            onGroupByProviderToggle={() => setGroupByProvider((prev) => !prev)}
          />
        </div>

        {/* Empty State */}
        {filteredModels.length === 0 && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <AlertCircle className="h-12 w-12 text-slate-300 dark:text-slate-600 mb-4" />
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-2">
              No models found
            </h3>
            <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md">
              Try adjusting your filters or search query to find models.
            </p>
          </div>
        )}

        {/* Models Grid (ungrouped) */}
        {!groupByProvider && filteredModels.length > 0 && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
            {filteredModels.map((model) => (
              <ModelCard
                key={model.id}
                model={model}
                isSelected={selectedModels.some((m) => m.id === model.id)}
                onSelect={handleModelSelect}
                onExpand={setExpandedModel}
              />
            ))}
          </div>
        )}

        {/* Models Grid (grouped) */}
        {groupByProvider && groupedModels && (
          <div className="space-y-8">
            {Object.entries(groupedModels).map(([provider, providerModels]) => (
              <div key={provider}>
                <h2 className="text-sm font-semibold text-slate-900 dark:text-slate-100 mb-4 capitalize flex items-center gap-2">
                  <span>{provider}</span>
                  <span className="text-xs text-slate-400 font-normal">
                    ({providerModels.length} model{providerModels.length !== 1 ? "s" : ""})
                  </span>
                </h2>
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-5">
                  {providerModels.map((model) => (
                    <ModelCard
                      key={model.id}
                      model={model}
                      isSelected={selectedModels.some((m) => m.id === model.id)}
                      onSelect={handleModelSelect}
                      onExpand={setExpandedModel}
                    />
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </main>

      {/* Comparison Panel */}
      {selectedModels.length > 0 && (
        <ModelComparison
          models={selectedModels}
          onClose={() => setSelectedModels([])}
          onRemoveModel={handleRemoveModel}
        />
      )}
    </div>
  );
}
