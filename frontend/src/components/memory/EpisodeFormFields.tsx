"use client";

import { FileText, Pin } from "lucide-react";
import { CompactnessMeter } from "@/components/CompactnessMeter";
import type { MemoryApplicability, MemoryContextKind } from "@/lib/memory-api";
import { cn } from "@/lib/utils";

interface EpisodeFormFieldsProps {
  summary: string;
  onSummaryChange: (value: string) => void;
  pinned: boolean;
  onPinnedChange: (value: boolean) => void;
  content: string;
  onContentChange: (value: string) => void;
  contextKind: MemoryContextKind;
  onContextKindChange: (value: MemoryContextKind) => void;
  applicability: MemoryApplicability;
  onApplicabilityChange: (value: MemoryApplicability) => void;
  triggerPhases: string[];
  onTriggerPhasesChange: (value: string[]) => void;
  episodeUuid: string;
  disabled?: boolean;
}

const CONTEXT_KIND_OPTIONS: Array<{
  value: MemoryContextKind;
  label: string;
  description: string;
}> = [
  { value: "policy", label: "Policy", description: "Hard or soft operating rules." },
  { value: "reference", label: "Reference", description: "Lookup knowledge for selective injection." },
  { value: "capability", label: "Capability", description: "Tool/control-surface catalog entries." },
  { value: "continuity", label: "Continuity", description: "Temporal state and follow-up context." },
  { value: "signal", label: "Signal", description: "Ratings, evidence, and curation signals." },
];

function parseList(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item, index, items) => item.length > 0 && items.indexOf(item) === index);
}

export function EpisodeFormFields({
  summary,
  onSummaryChange,
  pinned,
  onPinnedChange,
  content,
  onContentChange,
  contextKind,
  onContextKindChange,
  applicability,
  onApplicabilityChange,
  triggerPhases,
  onTriggerPhasesChange,
  episodeUuid,
  disabled,
}: EpisodeFormFieldsProps) {
  const handleApplicabilityChange = (
    field: keyof MemoryApplicability,
    value: string
  ) => {
    onApplicabilityChange({
      ...applicability,
      [field]: parseList(value),
    });
  };

  return (
    <>
      {/* Summary Field */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300 flex items-center gap-2">
          <FileText className="w-4 h-4 text-cyan-500" />
          Summary
          <span className="text-xs font-normal text-slate-400">(for TOON index)</span>
        </label>
        <input
          type="text"
          value={summary}
          onChange={(e) => onSummaryChange(e.target.value)}
          disabled={disabled}
          maxLength={40}
          className={cn(
            "w-full px-3 py-2.5 rounded-lg text-sm font-mono",
            "bg-slate-800/50",
            "border border-slate-700",
            "text-slate-100",
            "placeholder:text-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          placeholder="e.g., use dt for tests"
        />
        <p className="text-xs text-slate-400">
          Short action phrase (~20 chars) shown in reference index:{" "}
          <code className="text-cyan-400">
            {episodeUuid.slice(0, 8)}:{summary || "..."}
          </code>
        </p>
      </div>

      {/* Pinned Toggle */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Always Show</label>
        <button
          type="button"
          onClick={() => onPinnedChange(!pinned)}
          disabled={disabled}
          className={cn(
            "flex items-center gap-3 w-full px-3 py-2.5 rounded-lg border text-sm transition-all",
            pinned
              ? "border-violet-700 bg-violet-900/20"
              : "border-slate-700",
            "hover:ring-2 hover:ring-offset-1 hover:ring-slate-600",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          <Pin className={cn("w-4 h-4", pinned ? "text-violet-400" : "text-slate-400")} />
          <span className={pinned ? "text-violet-300 font-medium" : "text-slate-400"}>
            {pinned ? "Pinned (always shown)" : "Not pinned"}
          </span>
        </button>
        <p className="text-xs text-slate-400">
          Pinned episodes are always included when memory and this category are enabled, regardless of budget limits.
        </p>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">
          Context Channel
        </label>
        <select
          value={contextKind}
          onChange={(e) => onContextKindChange(e.target.value as MemoryContextKind)}
          disabled={disabled}
          className={cn(
            "w-full px-3 py-2.5 rounded-lg text-sm",
            "bg-slate-800/50 border border-slate-700 text-slate-100",
            "focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
        >
          {CONTEXT_KIND_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
        <p className="text-xs text-slate-400">
          {
            CONTEXT_KIND_OPTIONS.find((option) => option.value === contextKind)
              ?.description
          }
        </p>
      </div>

      <div className="space-y-3 rounded-lg border border-slate-700/70 bg-slate-900/40 p-4">
        <div>
          <h4 className="text-sm font-medium text-slate-200">
            Applicability
          </h4>
          <p className="text-xs text-slate-400">
            Leave fields blank for broad eligibility. Fill only the selectors
            required to keep this memory out of the wrong contexts.
          </p>
        </div>

        <div className="grid gap-3 md:grid-cols-2">
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Consumer Profiles
            </label>
            <input
              type="text"
              value={applicability.consumer_profiles.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange("consumer_profiles", e.target.value)
              }
              disabled={disabled}
              placeholder="agent_coding, agent_operator, codex_startup"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Exclude Profiles
            </label>
            <input
              type="text"
              value={applicability.exclude_consumer_profiles.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange(
                  "exclude_consumer_profiles",
                  e.target.value
                )
              }
              disabled={disabled}
              placeholder="agent_general, agent_visual"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Agent Slugs
            </label>
            <input
              type="text"
              value={applicability.agent_slugs.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange("agent_slugs", e.target.value)
              }
              disabled={disabled}
              placeholder="persona, coder, memory-curator"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Exclude Agents
            </label>
            <input
              type="text"
              value={applicability.exclude_agent_slugs.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange("exclude_agent_slugs", e.target.value)
              }
              disabled={disabled}
              placeholder="formatter, note-titler"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Audience Tags
            </label>
            <input
              type="text"
              value={applicability.audience_tags.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange("audience_tags", e.target.value)
              }
              disabled={disabled}
              placeholder="operator-tooling, codex-startup"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-400">
              Exclude Tags
            </label>
            <input
              type="text"
              value={applicability.exclude_audience_tags.join(", ")}
              onChange={(e) =>
                handleApplicabilityChange(
                  "exclude_audience_tags",
                  e.target.value
                )
              }
              disabled={disabled}
              placeholder="narrow-agent, runtime-light"
              className="w-full px-3 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 placeholder:text-slate-500"
            />
          </div>
        </div>
      </div>

      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">
          Trigger Phases
        </label>
        <input
          type="text"
          value={triggerPhases.join(", ")}
          onChange={(e) => onTriggerPhasesChange(parseList(e.target.value))}
          disabled={disabled}
          className={cn(
            "w-full px-3 py-2.5 rounded-lg text-sm",
            "bg-slate-800/50 border border-slate-700 text-slate-100",
            "focus:outline-none focus:ring-2 focus:ring-cyan-500/50 focus:border-cyan-500",
            "disabled:opacity-50 disabled:cursor-not-allowed"
          )}
          placeholder="e.g. diagnose, verify, closeout"
        />
        <p className="text-xs text-slate-400">
          Optional phase-specific activation for references and capability docs.
        </p>
      </div>

      {/* Content Editor */}
      <div className="space-y-2">
        <label className="text-sm font-medium text-slate-300">Content</label>
        <textarea
          value={content}
          onChange={(e) => onContentChange(e.target.value)}
          disabled={disabled}
          rows={8}
          className={cn(
            "w-full px-3 py-2.5 rounded-lg text-sm",
            "bg-slate-800/50",
            "border border-slate-700",
            "text-slate-100",
            "placeholder:text-slate-400",
            "focus:outline-none focus:ring-2 focus:ring-violet-500/50 focus:border-violet-500",
            "disabled:opacity-50 disabled:cursor-not-allowed",
            "resize-none"
          )}
          placeholder="Enter memory content..."
        />
        <p className="text-xs text-slate-400">{content.length} characters</p>
        <CompactnessMeter content={content} kind="memory" />
      </div>
    </>
  );
}
