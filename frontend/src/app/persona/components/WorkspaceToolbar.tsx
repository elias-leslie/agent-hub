"use client";

import { useId } from "react";
import { ArrowDown, ArrowUp, Filter, Search, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PersonaStreamMatch } from "@/lib/api/persona-stream";
import { type FilterMode } from "./pulse-helpers";
import { TimeRangeDropdown, type TimeRange } from "./TimeRangeDropdown";
import { HighlightedText, formatTimeLabel, shortenText } from "./workspace-utils";

interface WorkspaceToolbarProps {
  search: string;
  onSearchChange: (value: string) => void;
  timeRange: TimeRange;
  onTimeRangeChange: (value: TimeRange) => void;
  filterMode: FilterMode;
  setFilterMode: (mode: FilterMode) => void;
  showFilters: boolean;
  setShowFilters: (show: boolean) => void;
  filterCounts: Record<FilterMode, number>;
  deferredSearch: string;
  matchCount: number;
  activeSearchMatch: number;
  visibleSearchMatches: PersonaStreamMatch[];
  activeMatchId: string | null;
  onJumpToMatch: (direction: 1 | -1) => void;
  onSelectMatch: (entryId: string) => void;
}

const FILTER_OPTIONS: Array<[FilterMode, string]> = [
  ["all", "All"],
  ["messages", "Messages"],
  ["work", "Work"],
  ["heartbeats", "Heartbeats"],
  ["friction", "Friction"],
  ["errors", "Errors"],
  ["warnings", "Warnings"],
  ["stalled", "Stalled"],
  ["drift", "Drift"],
  ["tool_friction", "Tool Friction"],
  ["retries", "Retries"],
  ["recovered", "Recovered"],
  ["escalations", "Escalations"],
];

export function WorkspaceToolbar({
  search,
  onSearchChange,
  timeRange,
  onTimeRangeChange,
  filterMode,
  setFilterMode,
  showFilters,
  setShowFilters,
  filterCounts,
  deferredSearch,
  matchCount,
  activeSearchMatch,
  visibleSearchMatches,
  activeMatchId,
  onJumpToMatch,
  onSelectMatch,
}: WorkspaceToolbarProps) {
  const searchInputId = useId();

  const activeFilters = FILTER_OPTIONS.filter(([value]) => value !== "all" && filterCounts[value] > 0);
  const visibleFilters: Array<[FilterMode, string]> = [
    ["all", "All"],
    ["messages", "Messages"],
    ["work", "Work"],
    ["heartbeats", "Heartbeats"],
    ...activeFilters.filter(([v]) => !["all", "messages", "work", "heartbeats"].includes(v)),
  ];

  return (
    <div className="border-b border-slate-900/60 bg-slate-950/82 px-5 py-2">
      <div className="flex items-center gap-2.5">
        <div className="relative flex-1 min-w-0">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-500" />
          <input
            id={searchInputId}
            value={search}
            onChange={(event) => onSearchChange(event.target.value)}
            placeholder="Search history, tasks, files, agents..."
            className="w-full rounded-lg border border-slate-800/55 bg-slate-900/45 py-2 pl-9 pr-3 text-xs text-slate-200 outline-none transition-all placeholder:text-slate-500 focus:border-amber-500/30 focus:bg-slate-900/65 focus:ring-1 focus:ring-amber-500/20"
          />
        </div>
        <TimeRangeDropdown value={timeRange} onChange={onTimeRangeChange} />
        <button
          type="button"
          onClick={() => setShowFilters(!showFilters)}
          className={cn(
            "inline-flex items-center gap-1 rounded-lg p-2 text-xs transition-all",
            showFilters || filterMode !== "all"
              ? "bg-amber-500/10 text-amber-400 ring-1 ring-amber-500/20"
              : "text-slate-500 hover:bg-slate-800/60 hover:text-slate-300",
          )}
          title="Toggle filters"
        >
          <Filter className="h-3.5 w-3.5" />
        </button>
      </div>

      {filterMode !== "all" && !showFilters && (
        <div className="mt-2 flex items-center gap-2">
          <span className="text-[10px] text-slate-600">Showing:</span>
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-amber-500/10 ring-1 ring-amber-500/20 px-2.5 py-1 text-[10px] font-medium text-amber-300">
            {filterMode} ({filterCounts[filterMode]})
            <button type="button" onClick={() => setFilterMode("all")} className="ml-0.5 text-amber-500/50 hover:text-amber-300 transition-colors">
              <X className="h-3 w-3" />
            </button>
          </span>
        </div>
      )}

      {showFilters && (
        <div className="mt-2.5 flex flex-wrap items-center gap-2 pb-1">
          {visibleFilters.map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => { setFilterMode(value); setShowFilters(false); }}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[11px] font-medium transition-all",
                filterMode === value
                  ? "bg-amber-500/15 text-amber-300 ring-1 ring-amber-500/30"
                  : "bg-slate-800/40 text-slate-500 hover:bg-slate-800/60 hover:text-slate-300",
              )}
            >
              {label}
              {value !== "all" && <span className="opacity-60">{filterCounts[value]}</span>}
            </button>
          ))}
        </div>
      )}

      {deferredSearch.trim() && (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-lg border border-slate-700/40 bg-slate-900/60 px-3.5 py-2 text-xs text-slate-400">
          <span>
            {matchCount === 0
              ? `No matches for "${deferredSearch.trim()}"`
              : `${Math.max(activeSearchMatch, 0) + 1} of ${matchCount} matches`}
          </span>
          {matchCount > 0 && (
            <div className="flex items-center gap-0.5">
              <button type="button" onClick={() => onJumpToMatch(-1)} className="rounded-md p-1.5 transition-colors hover:bg-slate-800/80 hover:text-slate-200">
                <ArrowUp className="h-3.5 w-3.5" />
              </button>
              <button type="button" onClick={() => onJumpToMatch(1)} className="rounded-md p-1.5 transition-colors hover:bg-slate-800/80 hover:text-slate-200">
                <ArrowDown className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      )}

      {deferredSearch.trim() && visibleSearchMatches.length > 0 && (
        <div className="mt-2.5 flex flex-wrap gap-2">
          {visibleSearchMatches.map((match) => (
            <button
              key={match.entry_id}
              type="button"
              onClick={() => onSelectMatch(match.entry_id)}
              className={cn(
                "max-w-full rounded-xl border px-3 py-2 text-left text-[11px] transition-all",
                match.entry_id === activeMatchId
                  ? "border-amber-600/40 bg-amber-950/20 text-amber-100 shadow-sm shadow-amber-900/10"
                  : "border-slate-800/40 bg-slate-900/30 text-slate-400 hover:border-slate-700/50 hover:bg-slate-800/30",
              )}
            >
              <span className="font-medium uppercase tracking-wider text-[9px] text-slate-600">
                {formatTimeLabel(new Date(match.timestamp))} · {match.entry_type}
              </span>
              <HighlightedText text={shortenText(match.snippet, 90)} className="mt-0.5 block" />
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
