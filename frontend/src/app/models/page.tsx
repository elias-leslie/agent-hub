"use client";

import { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { Cpu, AlertCircle, Database, Loader2 } from "lucide-react";
import type { ModelOption } from "@agent-hub/chat-ui";
import { useModelsWithSync } from "@/components/chat/use-models";
import { fetchApi } from "@/lib/api-config";
import { useToastActions } from "@/components/error/toast";
import { ModelCard } from "@/components/models/model-card";
import { ModelFilters } from "@/components/models/model-filters";
import { ModelComparison } from "@/components/models/model-comparison";

export default function ModelsPage() {
  const {
    models,
    providers: allProviders,
    lastSync,
    lastModelReview,
    refetch,
    isLoading,
    isError,
  } = useModelsWithSync();
  const toast = useToastActions();
  const [syncing, setSyncing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  // null = "show all" until models load; becomes a Set after first initialization
  const [selectedProviders, setSelectedProviders] = useState<Set<string> | null>(null);
  const initialized = useRef(false);

  const availableProviders = useMemo(() => allProviders, [allProviders]);
  const availableProviderIds = useMemo(() => Object.keys(availableProviders), [availableProviders]);

  // Initialize selectedProviders to all available providers on first load
  useEffect(() => {
    if (!initialized.current && availableProviderIds.length > 0) {
      initialized.current = true;
      setSelectedProviders(new Set(availableProviderIds));
    }
  }, [availableProviderIds]);

  const effectiveSelectedProviders = selectedProviders ?? new Set(availableProviderIds);
  const [capabilityFilters, setCapabilityFilters] = useState({
    vision: false,
    imageGen: false,
    imageEdit: false,
    thinking: false,
    pdf: false,
    audio: false,
  });
  const [sortBy, setSortBy] = useState("composite");
  const [groupByProvider, setGroupByProvider] = useState(false);
  const [selectedModels, setSelectedModels] = useState<ModelOption[]>([]);
  const [, setExpandedModel] = useState<ModelOption | null>(null);

  const handleProviderToggle = (provider: string) => {
    setSelectedProviders((prev) => {
      const next = new Set(prev ?? availableProviderIds);
      if (next.has(provider)) {
        next.delete(provider);
      } else {
        next.add(provider);
      }
      return next;
    });
  };

  const handleCapabilityToggle = (capability: "vision" | "imageGen" | "imageEdit" | "thinking" | "pdf" | "audio") => {
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

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      await fetchApi("/api/models/sync", { method: "POST" });
      await refetch();
    } catch {
      toast.error("Sync failed", "Could not sync external benchmark data");
    } finally {
      setSyncing(false);
    }
  }, [refetch]);

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
    filtered = filtered.filter((model) => effectiveSelectedProviders.has(model.provider));

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
    if (capabilityFilters.thinking) {
      filtered = filtered.filter((model) => model.capabilities.has_thinking);
    }
    if (capabilityFilters.pdf) {
      filtered = filtered.filter((model) => model.capabilities.supports_pdf);
    }
    if (capabilityFilters.audio) {
      filtered = filtered.filter((model) => model.capabilities.supports_audio);
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
    <div className="min-h-screen bg-slate-950">
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2">
                <Cpu className="h-5 w-5 text-slate-400" />
                <h1 className="text-lg font-bold text-slate-100 tracking-tight">
                  Models
                </h1>
              </div>
              <div className="flex items-center gap-3 text-xs font-mono tabular-nums">
                <span className="text-slate-400">
                  {filteredModels.length} of {models.length} models
                </span>
              </div>
            </div>

            {/* Controls */}
            <div className="flex items-center gap-2">
              {lastSync && (
                <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                  Synced {new Date(lastSync).toLocaleDateString()}
                </span>
              )}
              {lastModelReview && (
                <span className="text-[10px] text-slate-400 dark:text-slate-500 font-mono">
                  Reviewed {new Date(lastModelReview).toLocaleDateString()}
                </span>
              )}
              <button
                type="button"
                onClick={handleSync}
                disabled={syncing}
                className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
                title="Sync external benchmark data"
              >
                {syncing ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Database className="h-3.5 w-3.5" />
                )}
                Sync
              </button>
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
            providers={availableProviders}
            selectedProviders={effectiveSelectedProviders}
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
        {isError && (
          <div className="flex items-center justify-center py-16 text-center">
            <div className="max-w-md">
              <AlertCircle className="h-12 w-12 text-red-400 mx-auto mb-4" />
              <h3 className="text-lg font-semibold text-slate-100 mb-2">
                Failed to load model catalog
              </h3>
              <p className="text-sm text-slate-400 mb-4">
                The models API request failed. Retry to refresh catalog data.
              </p>
              <button
                type="button"
                onClick={() => void refetch()}
                className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium border border-slate-700 bg-slate-800 text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors"
              >
                Retry
              </button>
            </div>
          </div>
        )}

        {isLoading && !isError && (
          <div className="flex items-center justify-center py-16 text-center">
            <div className="max-w-md">
              <Loader2 className="h-10 w-10 text-slate-400 animate-spin mx-auto mb-3" />
              <p className="text-sm text-slate-400">Loading models...</p>
            </div>
          </div>
        )}

        {filteredModels.length === 0 && !isError && !isLoading && (
          <div className="flex flex-col items-center justify-center py-16 text-center">
            <AlertCircle className="h-12 w-12 text-slate-600 mb-4" />
            <h3 className="text-lg font-semibold text-slate-100 mb-2">
              No models found
            </h3>
            <p className="text-sm text-slate-400 max-w-md">
              Try adjusting your filters or search query to find models.
            </p>
          </div>
        )}

        {/* Models Grid (ungrouped) */}
        {!groupByProvider && filteredModels.length > 0 && !isError && (
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
        {groupByProvider && groupedModels && !isError && (
          <div className="space-y-8">
            {Object.entries(groupedModels).map(([provider, providerModels]) => (
              <div key={provider}>
                <h2 className="text-sm font-semibold text-slate-100 mb-4 capitalize flex items-center gap-2">
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
