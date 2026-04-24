"use client";

import { useState, useMemo, useCallback, useEffect, useRef, useDeferredValue } from "react";
import { Cpu, AlertCircle, Database, Loader2, RefreshCw, Clock, Layers, Activity, Zap } from "lucide-react";
import { useModelsWithSync, type ModelOption } from "@/components/chat/use-models";
import { fetchApi } from "@/lib/api-config";
import { useToastActions } from "@/components/error/toast";
import { getPricingSortValue } from "@/lib/model-pricing";
import { ModelCard } from "@/components/models/model-card";
import { ModelFilters } from "@/components/models/model-filters";
import { ModelComparison } from "@/components/models/model-comparison";

function formatMoment(value: string | null): string {
  if (!value) return "Never";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function compactNumber(value: number | null | undefined): string {
  if (!value) return "0";
  return new Intl.NumberFormat(undefined, { notation: "compact" }).format(value);
}

function pricingSortValue(model: ModelOption): number {
  if (model.availability === "codex_only") return Number.POSITIVE_INFINITY;
  return getPricingSortValue(model.cost);
}

export default function ModelsPage() {
  const {
    models,
    providers: allProviders,
    lastSync,
    lastModelReview,
    catalogHealth,
    refetch,
    isLoading,
    isError,
  } = useModelsWithSync();
  const toast = useToastActions();
  const [syncing, setSyncing] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");
  const deferredSearchQuery = useDeferredValue(searchQuery);
  const [selectedProviders, setSelectedProviders] = useState<Set<string> | null>(null);
  const initialized = useRef(false);

  const availableProviders = useMemo(() => allProviders, [allProviders]);
  const availableProviderIds = useMemo(() => Object.keys(availableProviders), [availableProviders]);

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
      if (next.has(provider)) next.delete(provider);
      else next.add(provider);
      return next;
    });
  };

  const handleCapabilityToggle = (capability: "vision" | "imageGen" | "imageEdit" | "thinking" | "pdf" | "audio") => {
    setCapabilityFilters((prev) => ({ ...prev, [capability]: !prev[capability] }));
  };

  const handleModelSelect = (model: ModelOption) => {
    setSelectedModels((prev) => {
      const isSelected = prev.some((m) => m.id === model.id);
      if (isSelected) return prev.filter((m) => m.id !== model.id);
      if (prev.length >= 3) return prev;
      return [...prev, model];
    });
  };

  const handleSync = useCallback(async () => {
    setSyncing(true);
    try {
      const response = await fetchApi("/api/models/sync", { method: "POST" });
      if (!response.ok) throw new Error(`Sync failed: ${response.status}`);
      const result = await response.json();
      await refetch();
      toast.success(
        "Catalog synced",
        `${result.enriched ?? 0}/${result.total ?? 0} tracked models refreshed • ${result.discovery?.unmatched_model_count ?? 0} watchlist candidates`,
      );
    } catch {
      toast.error("Sync failed", "Could not refresh external benchmark and pricing overlays");
    } finally {
      setSyncing(false);
    }
  }, [refetch, toast]);

  const filteredModels = useMemo(() => {
    let filtered = models;

    if (deferredSearchQuery.trim()) {
      const query = deferredSearchQuery.toLowerCase();
      filtered = filtered.filter(
        (model) =>
          model.name.toLowerCase().includes(query) ||
          model.alias.toLowerCase().includes(query) ||
          model.hint.toLowerCase().includes(query),
      );
    }

    filtered = filtered.filter((model) => effectiveSelectedProviders.has(model.provider));

    if (capabilityFilters.vision) filtered = filtered.filter((model) => model.capabilities.has_vision);
    if (capabilityFilters.imageGen) filtered = filtered.filter((model) => model.capabilities.can_generate_images);
    if (capabilityFilters.imageEdit) filtered = filtered.filter((model) => model.capabilities.can_edit_images);
    if (capabilityFilters.thinking) filtered = filtered.filter((model) => model.capabilities.has_thinking);
    if (capabilityFilters.pdf) filtered = filtered.filter((model) => model.capabilities.supports_pdf);
    if (capabilityFilters.audio) filtered = filtered.filter((model) => model.capabilities.supports_audio);

    filtered = [...filtered].sort((a, b) => {
      switch (sortBy) {
        case "composite":
          return b.scores.composite - a.scores.composite;
        case "coding":
          return b.scores.coding - a.scores.coding;
        case "reasoning":
          return b.scores.reasoning - a.scores.reasoning;
        case "cost-asc":
          return pricingSortValue(a) - pricingSortValue(b);
        case "cost-desc":
          return pricingSortValue(b) - pricingSortValue(a);
        case "name":
          return a.name.localeCompare(b.name);
        default:
          return 0;
      }
    });

    return filtered;
  }, [models, deferredSearchQuery, effectiveSelectedProviders, capabilityFilters, sortBy]);

  const groupedModels = useMemo(() => {
    if (!groupByProvider) return null;
    const groups: Record<string, ModelOption[]> = {};
    for (const model of filteredModels) {
      if (!groups[model.provider]) groups[model.provider] = [];
      groups[model.provider].push(model);
    }
    return groups;
  }, [filteredModels, groupByProvider]);

  const summaryCards = [
    {
      label: "Tracked",
      value: compactNumber(catalogHealth?.total_models ?? models.length),
      detail: `${filteredModels.length} visible`,
      icon: Layers,
      tone: "from-amber-500/20 to-amber-500/5 border-amber-500/20 text-amber-100",
    },
    {
      label: "Live Pricing",
      value: compactNumber(catalogHealth?.models_with_live_pricing ?? 0),
      detail: `${catalogHealth?.models_missing_live_pricing ?? 0} still catalog-only`,
      icon: Database,
      tone: "from-emerald-500/20 to-emerald-500/5 border-emerald-500/20 text-emerald-100",
    },
    {
      label: "Freshness",
      value: catalogHealth?.is_stale ? "Stale" : "Fresh",
      detail: formatMoment(lastSync),
      icon: Clock,
      tone: catalogHealth?.is_stale
        ? "from-rose-500/20 to-rose-500/5 border-rose-500/20 text-rose-100"
        : "from-sky-500/20 to-sky-500/5 border-sky-500/20 text-sky-100",
    },
    {
      label: "Watchlist",
      value: compactNumber(catalogHealth?.discovery?.unmatched_model_count ?? 0),
      detail: `${catalogHealth?.discovery?.unmatched_provider_count ?? 0} tracked providers with new candidates`,
      icon: Activity,
      tone: "from-fuchsia-500/20 to-fuchsia-500/5 border-fuchsia-500/20 text-fuchsia-100",
    },
  ];

  const sourceCounts = catalogHealth?.source_counts ?? {};
  const discoveryProviders = catalogHealth?.discovery?.top_providers ?? [];

  return (
    <div className="page-shell">
      <div className="page-backdrop bg-grid-pattern opacity-40" />

      <main className="page-container px-4 py-6 lg:px-8">
        <section className="relative overflow-hidden rounded-[28px] border border-slate-800 bg-slate-950 shadow-[0_24px_80px_rgba(2,6,23,0.55)]">
          <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(245,158,11,0.16),transparent_34%),radial-gradient(circle_at_80%_18%,rgba(34,211,238,0.14),transparent_26%),linear-gradient(135deg,rgba(15,23,42,0.98),rgba(2,6,23,0.92))]" />
          <div className="relative p-6 lg:p-8">
            <div className="flex flex-col gap-6 xl:flex-row xl:items-start xl:justify-between">
              <div className="max-w-3xl space-y-4">
                <div className="inline-flex items-center gap-2 rounded-full border border-amber-500/20 bg-amber-500/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-200">
                  <Cpu className="h-3.5 w-3.5" />
                  Catalog Command Deck
                </div>
                <div className="space-y-3">
                  <h1 className="font-serif text-3xl tracking-tight text-slate-50 lg:text-4xl">
                    Model truth, GPT-5.5 readiness, price honesty.
                  </h1>
                  <p className="max-w-2xl text-sm leading-6 text-slate-300">
                    Curated registry stays authoritative. GPT-5.5 is routed through Codex OAuth until API
                    availability lands; sync overlays live pricing and benchmark evidence for API-backed models.
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <div className="rounded-2xl border border-slate-700/70 bg-slate-900/70 px-3 py-2 text-right">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">Last Sync</div>
                  <div className="text-sm font-medium text-slate-100">{formatMoment(lastSync)}</div>
                </div>
                <div className="rounded-2xl border border-emerald-400/20 bg-emerald-400/10 px-3 py-2 text-right">
                  <div className="text-[10px] uppercase tracking-[0.16em] text-emerald-300/70">Newest</div>
                  <div className="text-sm font-medium text-emerald-100">GPT-5.5 Codex-only</div>
                </div>
                <button
                  type="button"
                  onClick={handleSync}
                  disabled={syncing}
                  className="inline-flex items-center gap-2 rounded-2xl border border-cyan-400/20 bg-cyan-400/10 px-4 py-3 text-sm font-semibold text-cyan-100 transition hover:bg-cyan-400/15 disabled:opacity-60"
                >
                  {syncing ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
                  Sync External Sources
                </button>
                {selectedModels.length > 0 && (
                  <button
                    type="button"
                    onClick={() => setSelectedModels([])}
                    className="inline-flex items-center gap-2 rounded-2xl border border-amber-400/30 bg-amber-400/90 px-4 py-3 text-sm font-semibold text-slate-950 transition hover:bg-amber-300"
                  >
                    <Zap className="h-4 w-4" />
                    Compare {selectedModels.length}
                  </button>
                )}
              </div>
            </div>

            <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              {summaryCards.map(({ label, value, detail, icon: Icon, tone }) => (
                <article
                  key={label}
                  className={`rounded-[22px] border bg-gradient-to-br p-4 ${tone}`}
                >
                  <div className="flex items-start justify-between">
                    <div>
                      <p className="text-[11px] uppercase tracking-[0.16em] text-slate-300/80">{label}</p>
                      <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
                    </div>
                    <Icon className="h-5 w-5 text-current opacity-70" />
                  </div>
                  <p className="mt-4 text-xs leading-5 text-slate-300/80">{detail}</p>
                </article>
              ))}
            </div>

            <div className="mt-6 grid gap-4 xl:grid-cols-[1.2fr_0.8fr]">
              <section className="rounded-[24px] border border-slate-800/80 bg-slate-950/70 p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Source coverage</p>
                    <h2 className="mt-2 text-lg font-semibold text-slate-100">Current ingest footprint</h2>
                  </div>
                  <Database className="h-5 w-5 text-slate-500" />
                </div>
                <div className="mt-4 grid gap-3 sm:grid-cols-4">
                  {[
                    ["models.dev", sourceCounts.models_dev ?? 0],
                    ["benchmarks", sourceCounts.benchmarks ?? 0],
                    ["BFCL", sourceCounts.bfcl ?? 0],
                    ["LiveBench", sourceCounts.livebench ?? 0],
                  ].map(([label, value]) => (
                    <div key={label} className="rounded-2xl border border-slate-800 bg-slate-900/80 p-3">
                      <div className="text-[10px] uppercase tracking-[0.16em] text-slate-500">{label}</div>
                      <div className="mt-2 text-xl font-semibold text-slate-100">{compactNumber(Number(value))}</div>
                    </div>
                  ))}
                </div>
                <div className="mt-4 flex flex-wrap gap-2 text-xs text-slate-400">
                  <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5">
                    Review log: {formatMoment(lastModelReview)}
                  </span>
                  <span className="rounded-full border border-slate-800 bg-slate-900 px-3 py-1.5">
                    Sync status: {catalogHealth?.sync_status ?? "unknown"}
                  </span>
                </div>
              </section>

              <section className="rounded-[24px] border border-slate-800/80 bg-slate-950/70 p-5">
                <div className="flex items-center justify-between">
                  <div>
                    <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">Discovery watchlist</p>
                    <h2 className="mt-2 text-lg font-semibold text-slate-100">External candidates not in catalog</h2>
                  </div>
                  <Activity className="h-5 w-5 text-slate-500" />
                </div>

                {discoveryProviders.length === 0 ? (
                  <div className="mt-5 rounded-2xl border border-slate-800 bg-slate-900/80 p-4 text-sm text-slate-400">
                    No tracked-provider candidates flagged in the last sync.
                  </div>
                ) : (
                  <div className="mt-4 space-y-3">
                    {discoveryProviders.map((provider) => (
                      <article key={provider.provider_id} className="rounded-2xl border border-slate-800 bg-slate-900/80 p-4">
                        <div className="flex items-center justify-between gap-3">
                          <div>
                            <p className="text-sm font-semibold text-slate-100">{provider.provider_name}</p>
                            <p className="text-[11px] uppercase tracking-[0.16em] text-slate-500">{provider.provider_id}</p>
                          </div>
                          <span className="rounded-full border border-fuchsia-500/20 bg-fuchsia-500/10 px-2.5 py-1 text-xs font-semibold text-fuchsia-200">
                            {provider.unmatched_count} candidates
                          </span>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-2">
                          {provider.sample_model_ids.map((sample) => (
                            <span key={sample} className="rounded-full border border-slate-800 bg-slate-950 px-2.5 py-1 font-mono text-[11px] text-slate-300">
                              {sample}
                            </span>
                          ))}
                        </div>
                      </article>
                    ))}
                  </div>
                )}
              </section>
            </div>
          </div>
        </section>

        <section className="mt-6 rounded-[24px] border border-slate-800 bg-slate-950/90 p-4 shadow-[0_18px_60px_rgba(2,6,23,0.35)]">
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
        </section>

        {isError && (
          <div className="mt-6 flex items-center justify-center py-16 text-center">
            <div className="max-w-md rounded-[24px] border border-rose-900/60 bg-rose-950/20 p-8">
              <AlertCircle className="mx-auto mb-4 h-12 w-12 text-rose-400" />
              <h3 className="text-lg font-semibold text-slate-100">Failed to load model catalog</h3>
              <p className="mt-2 text-sm text-slate-400">
                Models API did not return catalog data. Retry after backend check.
              </p>
              <button
                type="button"
                onClick={() => void refetch()}
                className="mt-5 inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-sm font-medium text-slate-200 transition hover:bg-slate-800"
              >
                <RefreshCw className="h-4 w-4" />
                Retry
              </button>
            </div>
          </div>
        )}

        {isLoading && !isError && (
          <div className="mt-6 flex items-center justify-center py-16 text-center">
            <div className="max-w-md rounded-[24px] border border-slate-800 bg-slate-950/80 p-8">
              <Loader2 className="mx-auto mb-4 h-10 w-10 animate-spin text-slate-400" />
              <p className="text-sm text-slate-400">Loading model catalog...</p>
            </div>
          </div>
        )}

        {filteredModels.length === 0 && !isError && !isLoading && (
          <div className="mt-6 flex flex-col items-center justify-center rounded-[24px] border border-slate-800 bg-slate-950/80 py-16 text-center">
            <AlertCircle className="mb-4 h-12 w-12 text-slate-600" />
            <h3 className="text-lg font-semibold text-slate-100">No models found</h3>
            <p className="mt-2 max-w-md text-sm text-slate-400">
              Current filters excluded every catalog entry. Change provider, capability, or search.
            </p>
          </div>
        )}

        {!groupByProvider && filteredModels.length > 0 && !isError && (
          <div className="mt-6 grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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

        {groupByProvider && groupedModels && !isError && (
          <div className="mt-6 space-y-8">
            {Object.entries(groupedModels).map(([provider, providerModels]) => (
              <section key={provider} className="rounded-[24px] border border-slate-800 bg-slate-950/70 p-5">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <h2 className="text-lg font-semibold capitalize text-slate-100">{provider}</h2>
                    <p className="text-xs uppercase tracking-[0.16em] text-slate-500">
                      {providerModels.length} models in current filter set
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-5 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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
              </section>
            ))}
          </div>
        )}

        <ModelComparison
          models={selectedModels}
          onClose={() => setSelectedModels([])}
          onRemoveModel={(modelId) => setSelectedModels((prev) => prev.filter((m) => m.id !== modelId))}
        />
      </main>
    </div>
  );
}
