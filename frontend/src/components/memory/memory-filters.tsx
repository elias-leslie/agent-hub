"use client";

import { ChevronDown, Search, X } from "lucide-react";
import { useState, useRef, useEffect } from "react";
import { cn } from "@/lib/utils";
import type { MemoryCategory, MemoryScope, MemoryGroup } from "@/lib/memory-api";

interface MemoryFiltersProps {
  groups: MemoryGroup[];
  selectedGroup: string | undefined;
  onGroupChange: (groupId: string | undefined) => void;
  selectedScope: MemoryScope | undefined;
  onScopeChange: (scope: MemoryScope | undefined) => void;
  selectedCategory: MemoryCategory | undefined;
  onCategoryChange: (category: MemoryCategory | undefined) => void;
  searchQuery: string;
  onSearchChange: (query: string) => void;
  isSearching: boolean;
}

const SCOPES: { id: MemoryScope | "all"; label: string }[] = [
  { id: "all", label: "All Scopes" },
  { id: "global", label: "Global" },
  { id: "project", label: "Project" },
  { id: "task", label: "Task" },
];

const CATEGORIES: { id: MemoryCategory | "all"; label: string; icon: string }[] = [
  { id: "all", label: "All", icon: "📋" },
  { id: "coding_standard", label: "Standards", icon: "📏" },
  { id: "troubleshooting_guide", label: "Gotchas", icon: "⚠️" },
  { id: "system_design", label: "Design", icon: "🏗️" },
  { id: "operational_context", label: "Ops", icon: "⚙️" },
  { id: "domain_knowledge", label: "Domain", icon: "📚" },
  { id: "active_state", label: "Active", icon: "▶️" },
];

export function MemoryFilters({
  groups,
  selectedGroup,
  onGroupChange,
  selectedScope,
  onScopeChange,
  selectedCategory,
  onCategoryChange,
  searchQuery,
  onSearchChange,
  isSearching,
}: MemoryFiltersProps) {
  const [groupDropdownOpen, setGroupDropdownOpen] = useState(false);
  const [scopeDropdownOpen, setScopeDropdownOpen] = useState(false);
  const groupDropdownRef = useRef<HTMLDivElement>(null);
  const scopeDropdownRef = useRef<HTMLDivElement>(null);

  // Close dropdowns on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (groupDropdownRef.current && !groupDropdownRef.current.contains(e.target as Node)) {
        setGroupDropdownOpen(false);
      }
      if (scopeDropdownRef.current && !scopeDropdownRef.current.contains(e.target as Node)) {
        setScopeDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  const selectedGroupName = selectedGroup
    ? groups.find((g) => g.group_id === selectedGroup)?.group_id || selectedGroup
    : "All Groups";

  const selectedScopeName = selectedScope
    ? SCOPES.find((s) => s.id === selectedScope)?.label || selectedScope
    : "All Scopes";

  return (
    <div className="space-y-4">
      {/* Search and Group selector row */}
      <div className="flex flex-col sm:flex-row gap-3">
        {/* Search */}
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            placeholder="Search memories..."
            className={cn(
              "w-full pl-10 pr-10 py-2 rounded-lg",
              "bg-white dark:bg-slate-900",
              "border border-slate-200 dark:border-slate-700",
              "text-slate-900 dark:text-slate-100",
              "placeholder:text-slate-400 dark:placeholder:text-slate-500",
              "focus:outline-none focus:ring-2 focus:ring-emerald-500/50",
            )}
            data-testid="memory-search"
          />
          {searchQuery && (
            <button
              onClick={() => onSearchChange("")}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
            >
              <X className="w-4 h-4" />
            </button>
          )}
          {isSearching && (
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <div className="w-4 h-4 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
            </div>
          )}
        </div>

        {/* Scope selector */}
        <div className="relative" ref={scopeDropdownRef} data-testid="scope-filter">
          <button
            onClick={() => setScopeDropdownOpen(!scopeDropdownOpen)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg min-w-[140px]",
              "bg-white dark:bg-slate-900",
              "border border-slate-200 dark:border-slate-700",
              "text-slate-900 dark:text-slate-100",
              "hover:border-slate-300 dark:hover:border-slate-600",
            )}
          >
            <span className="flex-1 text-left truncate">{selectedScopeName}</span>
            <ChevronDown className={cn("w-4 h-4 transition-transform", scopeDropdownOpen && "rotate-180")} />
          </button>
          {scopeDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-full min-w-[140px] rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-lg z-10">
              {SCOPES.map((scope) => {
                const isSelected = scope.id === "all" ? !selectedScope : selectedScope === scope.id;
                return (
                  <button
                    key={scope.id}
                    onClick={() => {
                      onScopeChange(scope.id === "all" ? undefined : scope.id);
                      setScopeDropdownOpen(false);
                    }}
                    className={cn(
                      "w-full px-4 py-2 text-left text-sm",
                      "hover:bg-slate-100 dark:hover:bg-slate-800",
                      isSelected && "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300",
                    )}
                  >
                    {scope.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

        {/* Group selector */}
        <div className="relative" ref={groupDropdownRef} data-testid="group-selector">
          <button
            onClick={() => setGroupDropdownOpen(!groupDropdownOpen)}
            className={cn(
              "flex items-center gap-2 px-4 py-2 rounded-lg min-w-[160px]",
              "bg-white dark:bg-slate-900",
              "border border-slate-200 dark:border-slate-700",
              "text-slate-900 dark:text-slate-100",
              "hover:border-slate-300 dark:hover:border-slate-600",
            )}
          >
            <span className="flex-1 text-left truncate">{selectedGroupName}</span>
            <ChevronDown className={cn("w-4 h-4 transition-transform", groupDropdownOpen && "rotate-180")} />
          </button>
          {groupDropdownOpen && (
            <div className="absolute top-full left-0 mt-1 w-full min-w-[200px] rounded-lg bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 shadow-lg z-10">
              <button
                onClick={() => {
                  onGroupChange(undefined);
                  setGroupDropdownOpen(false);
                }}
                className={cn(
                  "w-full px-4 py-2 text-left text-sm",
                  "hover:bg-slate-100 dark:hover:bg-slate-800",
                  !selectedGroup && "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300",
                )}
              >
                All Groups
              </button>
              {groups.map((group) => (
                <button
                  key={group.group_id}
                  onClick={() => {
                    onGroupChange(group.group_id);
                    setGroupDropdownOpen(false);
                  }}
                  className={cn(
                    "w-full px-4 py-2 text-left text-sm flex justify-between",
                    "hover:bg-slate-100 dark:hover:bg-slate-800",
                    selectedGroup === group.group_id &&
                      "bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300",
                  )}
                >
                  <span className="truncate">{group.group_id}</span>
                  <span className="text-slate-400 dark:text-slate-500 ml-2">
                    {group.episode_count}
                  </span>
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Category chips */}
      <div className="flex flex-wrap gap-2" data-testid="category-filter">
        {CATEGORIES.map((cat) => {
          const isSelected = cat.id === "all" ? !selectedCategory : selectedCategory === cat.id;
          return (
            <button
              key={cat.id}
              onClick={() => onCategoryChange(cat.id === "all" ? undefined : cat.id)}
              className={cn(
                "px-3 py-1.5 rounded-full text-sm font-medium transition-colors",
                isSelected
                  ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border border-emerald-300 dark:border-emerald-700"
                  : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border border-transparent hover:border-slate-300 dark:hover:border-slate-600",
              )}
            >
              <span className="mr-1">{cat.icon}</span>
              {cat.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
