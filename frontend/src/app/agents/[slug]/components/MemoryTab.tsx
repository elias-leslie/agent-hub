"use client";

import { Brain, Settings2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { Agent } from "../types";
import { parseConfig } from "./memory/utils";
import { DEFAULT_CONFIG } from "./memory/constants";
import { Toggle } from "./memory/Toggle";
import { MemoryConfigSection } from "./memory/MemoryConfigSection";
import { TagFilteringSection } from "./memory/TagFilteringSection";
import { MemoryConfig } from "./memory/types";

interface MemoryTabProps {
  formData: Partial<Agent>;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
}

export function MemoryTab({ formData, updateField }: MemoryTabProps) {
  const isCustomEnabled = formData.memory_config != null;
  const config = parseConfig(formData.memory_config ?? null);

  const updateConfig = (updates: Partial<MemoryConfig>) => {
    const newConfig = { ...config, ...updates };
    updateField("memory_config", newConfig);
  };

  const toggleCustomSettings = () => {
    if (isCustomEnabled) {
      updateField("memory_config", null);
    } else {
      updateField("memory_config", { ...DEFAULT_CONFIG });
    }
  };

  const handleUpdateTags = (
    field: "include_tags" | "exclude_tags",
    tags: string[]
  ) => {
    if (isCustomEnabled) {
      updateConfig({ [field]: tags });
    } else {
      const otherField =
        field === "include_tags" ? "exclude_tags" : "include_tags";
      const otherTags = config[otherField];

      if (tags.length === 0 && otherTags.length === 0) {
        updateField("memory_config", null);
      } else {
        updateField(
          "memory_config",
          {
            ...DEFAULT_CONFIG,
            [field]: tags,
            [otherField]: otherTags,
            _tags_only: true,
          }
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
      <MemoryConfigSection
        config={config}
        isCustomEnabled={isCustomEnabled}
        onUpdateConfig={updateConfig}
      />

      {/* Tag Filtering Section */}
      <TagFilteringSection
        includeTags={config.include_tags}
        excludeTags={config.exclude_tags}
        onUpdateTags={handleUpdateTags}
      />
    </div>
  );
}
