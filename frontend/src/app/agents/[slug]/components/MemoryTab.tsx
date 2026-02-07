"use client";

import { Brain, Tags, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Agent } from "../types";

interface MemoryTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

interface MemoryConfig {
  injection_enabled: boolean;
  budget_enforcement: boolean;
  token_budget: number;
  max_mandates: number;
  max_guardrails: number;
  reference_index: boolean;
  include_tags: string[];
  exclude_tags: string[];
}

const DEFAULT_CONFIG: MemoryConfig = {
  injection_enabled: true,
  budget_enforcement: true,
  token_budget: 3500,
  max_mandates: 0,
  max_guardrails: 0,
  reference_index: true,
  include_tags: [],
  exclude_tags: [],
};

function parseConfig(raw: Record<string, unknown> | null): MemoryConfig {
  if (!raw) return { ...DEFAULT_CONFIG };
  return {
    injection_enabled: (raw.injection_enabled as boolean) ?? true,
    budget_enforcement: (raw.budget_enforcement as boolean) ?? true,
    token_budget: (raw.token_budget as number) ?? 3500,
    max_mandates: (raw.max_mandates as number) ?? 0,
    max_guardrails: (raw.max_guardrails as number) ?? 0,
    reference_index: (raw.reference_index as boolean) ?? true,
    include_tags: (raw.include_tags as string[]) ?? [],
    exclude_tags: (raw.exclude_tags as string[]) ?? [],
  };
}

function Toggle({
  enabled,
  onToggle,
  disabled,
}: {
  enabled: boolean;
  onToggle: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={() => !disabled && onToggle()}
      className={cn(
        "relative inline-flex h-6 w-11 items-center rounded-full transition-colors",
        enabled ? "bg-blue-600" : "bg-slate-300 dark:bg-slate-600",
        disabled && "opacity-50 cursor-not-allowed"
      )}
    >
      <span
        className={cn(
          "inline-block h-4 w-4 transform rounded-full bg-white transition-transform",
          enabled ? "translate-x-6" : "translate-x-1"
        )}
      />
    </button>
  );
}

export function MemoryTab({ formData, updateField }: MemoryTabProps) {
  const isCustomEnabled = formData.memory_config != null;
  const config = parseConfig(
    (formData.memory_config as Record<string, unknown> | null) ?? null
  );

  const updateConfig = (updates: Partial<MemoryConfig>) => {
    const newConfig = { ...config, ...updates };
    updateField("memory_config", newConfig as unknown as Agent["memory_config"]);
  };

  const toggleCustomSettings = () => {
    if (isCustomEnabled) {
      // Turning off: preserve tag filters, set memory_config to null
      updateField("memory_config", null);
    } else {
      // Turning on: initialize with defaults
      updateField(
        "memory_config",
        { ...DEFAULT_CONFIG } as unknown as Agent["memory_config"]
      );
    }
  };

  // Tag filtering reads from config if custom is enabled,
  // otherwise we need a way to store tags independently.
  // Since tags are always visible, we store them in memory_config too.
  // When custom is OFF but tags exist, we use a minimal config with just tags.
  const includeTags = config.include_tags;
  const excludeTags = config.exclude_tags;

  const updateTags = (
    field: "include_tags" | "exclude_tags",
    value: string
  ) => {
    const tags = value
      .split(",")
      .map((t) => t.trim())
      .filter((t) => t.length > 0);

    if (isCustomEnabled) {
      updateConfig({ [field]: tags });
    } else {
      // When custom settings are OFF, store a minimal config with just tags
      const otherField =
        field === "include_tags" ? "exclude_tags" : "include_tags";
      const otherTags =
        field === "include_tags" ? excludeTags : includeTags;

      if (tags.length === 0 && otherTags.length === 0) {
        // No tags at all, keep null
        updateField("memory_config", null);
      } else {
        updateField(
          "memory_config",
          {
            ...DEFAULT_CONFIG,
            [field]: tags,
            [otherField]: otherTags,
            _tags_only: true,
          } as unknown as Agent["memory_config"]
        );
      }
    }
  };

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 flex items-center gap-2">
          <Brain className="h-5 w-5 text-slate-400" />
          Memory Configuration
        </h2>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          Control how memory episodes are injected into this agent&apos;s
          context
        </p>
      </div>

      {/* Custom Settings Toggle */}
      <div className="flex items-center justify-between p-4 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50">
        <div className="flex items-center gap-3">
          <Settings2 className="h-5 w-5 text-slate-400" />
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
              Enable Custom Memory Settings
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              {isCustomEnabled
                ? "Using per-agent memory configuration"
                : "Using global memory settings"}
            </p>
          </div>
        </div>
        <Toggle enabled={isCustomEnabled} onToggle={toggleCustomSettings} />
      </div>

      {/* Settings Panel */}
      <div
        className={cn(
          "space-y-5 p-5 rounded-lg border",
          isCustomEnabled
            ? "border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50"
            : "border-slate-200 dark:border-slate-700/50 bg-slate-50 dark:bg-slate-800/20 opacity-50 pointer-events-none"
        )}
      >
        <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
          Injection Settings
        </h3>

        {/* Injection Enabled */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Injection Enabled
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Inject memory episodes into agent context
            </p>
          </div>
          <Toggle
            enabled={config.injection_enabled}
            onToggle={() =>
              updateConfig({ injection_enabled: !config.injection_enabled })
            }
            disabled={!isCustomEnabled}
          />
        </div>

        {/* Budget Enforcement */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Budget Enforcement
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Enforce token budget limits on injected context
            </p>
          </div>
          <Toggle
            enabled={config.budget_enforcement}
            onToggle={() =>
              updateConfig({ budget_enforcement: !config.budget_enforcement })
            }
            disabled={!isCustomEnabled}
          />
        </div>

        {/* Token Budget Slider */}
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <label className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Token Budget
            </label>
            <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
              {config.token_budget.toLocaleString()}
            </span>
          </div>
          <input
            type="range"
            min="100"
            max="10000"
            step="100"
            value={config.token_budget}
            onChange={(e) =>
              updateConfig({ token_budget: parseInt(e.target.value) })
            }
            disabled={!isCustomEnabled}
            className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
          />
          <div className="flex justify-between text-[10px] text-slate-400">
            <span>100</span>
            <span>5,000</span>
            <span>10,000</span>
          </div>
        </div>

        {/* Max Mandates */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Max Mandates
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Maximum mandate episodes to inject (0 = unlimited)
            </p>
          </div>
          <input
            type="number"
            min="0"
            value={config.max_mandates}
            onChange={(e) =>
              updateConfig({
                max_mandates: Math.max(0, parseInt(e.target.value) || 0),
              })
            }
            disabled={!isCustomEnabled}
            className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500/40"
          />
        </div>

        {/* Max Guardrails */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Max Guardrails
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Maximum guardrail episodes to inject (0 = unlimited)
            </p>
          </div>
          <input
            type="number"
            min="0"
            value={config.max_guardrails}
            onChange={(e) =>
              updateConfig({
                max_guardrails: Math.max(0, parseInt(e.target.value) || 0),
              })
            }
            disabled={!isCustomEnabled}
            className="w-20 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm text-right focus:outline-none focus:ring-2 focus:ring-blue-500/40"
          />
        </div>

        {/* Reference Index */}
        <div className="flex items-center justify-between">
          <div>
            <p className="text-sm font-medium text-slate-900 dark:text-slate-200">
              Reference Index
            </p>
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Include reference episode index in context
            </p>
          </div>
          <Toggle
            enabled={config.reference_index}
            onToggle={() =>
              updateConfig({ reference_index: !config.reference_index })
            }
            disabled={!isCustomEnabled}
          />
        </div>
      </div>

      {/* Tag Filtering Section - ALWAYS visible */}
      <div className="space-y-5 p-5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800/50">
        <div className="flex items-center gap-2">
          <Tags className="h-5 w-5 text-slate-400" />
          <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 uppercase tracking-wider">
            Tag Filtering
          </h3>
        </div>

        <p className="text-xs text-slate-500 dark:text-slate-400">
          Include = only inject these tagged episodes. Exclude = never inject
          these tagged episodes.
        </p>

        {/* Include Tags */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Include Tags
          </label>
          <input
            type="text"
            value={includeTags.join(", ")}
            onChange={(e) => updateTags("include_tags", e.target.value)}
            placeholder="e.g. python, deployment, security"
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 placeholder:text-slate-400 dark:placeholder:text-slate-500"
          />
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            Comma-separated whitelist of episode tags
          </p>
        </div>

        {/* Exclude Tags */}
        <div className="space-y-1.5">
          <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
            Exclude Tags
          </label>
          <input
            type="text"
            value={excludeTags.join(", ")}
            onChange={(e) => updateTags("exclude_tags", e.target.value)}
            placeholder="e.g. deprecated, internal, draft"
            className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 placeholder:text-slate-400 dark:placeholder:text-slate-500"
          />
          <p className="text-[11px] text-slate-400 dark:text-slate-500">
            Comma-separated blacklist of episode tags
          </p>
        </div>
      </div>
    </div>
  );
}
