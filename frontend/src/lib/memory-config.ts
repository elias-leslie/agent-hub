/**
 * Shared configuration and constants for the Memory system
 */

import type { MemoryCategory, MemoryScope } from './memory-api'

// ─────────────────────────────────────────────────────────────────────────────
// CATEGORY CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

export const CATEGORY_CONFIG: Record<
  MemoryCategory,
  {
    icon: string
    label: string
    color: string
    bg: string
    description: string
  }
> = {
  mandate: {
    icon: '🔒',
    label: 'Mandate',
    color: 'text-red-400',
    bg: 'bg-red-500/10 border-red-400/40',
    description: 'Always injected — golden standards',
  },
  guardrail: {
    icon: '⚠️',
    label: 'Guardrail',
    color: 'text-amber-400',
    bg: 'bg-amber-500/10 border-amber-400/40',
    description: 'Always injected — safety rules',
  },
  reference: {
    icon: '📚',
    label: 'Reference',
    color: 'text-amber-400',
    bg: 'bg-blue-500/10 border-blue-400/40',
    description: 'On-demand — triggered or searched',
  },
  archive: {
    icon: '🗄️',
    label: 'Archive',
    color: 'text-slate-400',
    bg: 'bg-slate-500/10 border-slate-400/40',
    description: 'Cold storage — demoted, low-priority',
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// SCOPE CONFIGURATION
// ─────────────────────────────────────────────────────────────────────────────

export const SCOPE_CONFIG: Record<
  MemoryScope,
  { label: string; color: string; bg: string }
> = {
  global: {
    label: 'Global',
    color: 'text-indigo-600 dark:text-indigo-400',
    bg: 'bg-indigo-500/10 border-indigo-400/40',
  },
  project: {
    label: 'Project',
    color: 'text-teal-400',
    bg: 'bg-teal-500/10 border-teal-400/40',
  },
  task: {
    label: 'Task',
    color: 'text-orange-400',
    bg: 'bg-orange-500/10 border-orange-400/40',
  },
}

// ─────────────────────────────────────────────────────────────────────────────
// LOCAL STORAGE KEYS
// ─────────────────────────────────────────────────────────────────────────────

export const SORT_STORAGE_KEY = 'memory-sort'
export const SEARCH_STORAGE_KEY = 'memory-search'
export const TIMELINE_COLLAPSE_KEY = 'memory-timeline-collapsed'
