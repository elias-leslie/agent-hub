/**
 * Shared configuration and constants for the Memory system
 */

import type { MemoryCategory, MemoryScope } from "./memory-api";

// ─────────────────────────────────────────────────────────────────────────────
// CATEGORY CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

export const CATEGORY_CONFIG: Record<
  MemoryCategory,
  { icon: string; label: string; color: string; bg: string }
> = {
  coding_standard: {
    icon: "📏",
    label: "Standard",
    color: "text-blue-600 dark:text-blue-400",
    bg: "bg-blue-500/10 border-blue-400/40",
  },
  troubleshooting_guide: {
    icon: "⚠️",
    label: "Gotcha",
    color: "text-amber-600 dark:text-amber-400",
    bg: "bg-amber-500/10 border-amber-400/40",
  },
  system_design: {
    icon: "🏗️",
    label: "Design",
    color: "text-purple-600 dark:text-purple-400",
    bg: "bg-purple-500/10 border-purple-400/40",
  },
  operational_context: {
    icon: "⚙️",
    label: "Ops",
    color: "text-slate-600 dark:text-slate-400",
    bg: "bg-slate-500/10 border-slate-400/40",
  },
  domain_knowledge: {
    icon: "📚",
    label: "Domain",
    color: "text-emerald-600 dark:text-emerald-400",
    bg: "bg-emerald-500/10 border-emerald-400/40",
  },
  active_state: {
    icon: "▶️",
    label: "Active",
    color: "text-cyan-600 dark:text-cyan-400",
    bg: "bg-cyan-500/10 border-cyan-400/40",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// SCOPE CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

export const SCOPE_CONFIG: Record<MemoryScope, { label: string; color: string; bg: string }> = {
  global: {
    label: "Global",
    color: "text-indigo-600 dark:text-indigo-400",
    bg: "bg-indigo-500/10 border-indigo-400/40",
  },
  project: {
    label: "Project",
    color: "text-teal-600 dark:text-teal-400",
    bg: "bg-teal-500/10 border-teal-400/40",
  },
  task: {
    label: "Task",
    color: "text-orange-600 dark:text-orange-400",
    bg: "bg-orange-500/10 border-orange-400/40",
  },
};

// ─────────────────────────────────────────────────────────────────────────────
// REFRESH OPTIONS
// ─────────────────────────────────────────────────────────────────────────────

export const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 5000, label: "5s" },
  { value: 15000, label: "15s" },
  { value: 30000, label: "30s" },
  { value: 60000, label: "60s" },
] as const;

export type RefreshInterval = (typeof REFRESH_OPTIONS)[number]["value"];

// ─────────────────────────────────────────────────────────────────────────────
// LOCAL STORAGE KEYS
// ─────────────────────────────────────────────────────────────────────────────

export const REFRESH_STORAGE_KEY = "memory-auto-refresh";
export const SORT_STORAGE_KEY = "memory-sort";
