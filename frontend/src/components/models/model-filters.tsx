'use client'

import {
  Brain,
  Camera,
  Eye,
  FileText,
  Headphones,
  Pencil,
  Search,
} from 'lucide-react'
import { PROVIDER_COLORS } from '@/components/settings/constants'
import { cn } from '@/lib/utils'

interface CapabilityFilters {
  vision: boolean
  imageGen: boolean
  imageEdit: boolean
  thinking: boolean
  pdf: boolean
  audio: boolean
}

interface ModelFiltersProps {
  searchQuery: string
  onSearchChange: (query: string) => void
  providers: Record<string, string>
  selectedProviders: Set<string>
  onProviderToggle: (provider: string) => void
  capabilityFilters: CapabilityFilters
  onCapabilityToggle: (capability: keyof CapabilityFilters) => void
  sortBy: string
  onSortChange: (sort: string) => void
  groupByProvider: boolean
  onGroupByProviderToggle: () => void
}

const SORT_OPTIONS = [
  { value: 'composite', label: 'Composite Score' },
  { value: 'coding', label: 'Coding Score' },
  { value: 'reasoning', label: 'Reasoning Score' },
  { value: 'cost-asc', label: 'Cost (Low to High)' },
  { value: 'cost-desc', label: 'Cost (High to Low)' },
  { value: 'name', label: 'Name' },
]

const CAPABILITY_BUTTONS: {
  key: keyof CapabilityFilters
  label: string
  icon: typeof Eye
  activeClass: string
}[] = [
  {
    key: 'vision',
    label: 'Vision',
    icon: Eye,
    activeClass: 'bg-amber-500/10 text-amber-400 border-amber-500/20',
  },
  {
    key: 'thinking',
    label: 'Thinking',
    icon: Brain,
    activeClass: 'bg-violet-500/10 text-violet-400 border-violet-500/20',
  },
  {
    key: 'imageGen',
    label: 'Image Gen',
    icon: Camera,
    activeClass: 'bg-purple-500/10 text-purple-400 border-purple-500/20',
  },
  {
    key: 'pdf',
    label: 'PDF',
    icon: FileText,
    activeClass: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  },
  {
    key: 'audio',
    label: 'Audio',
    icon: Headphones,
    activeClass: 'bg-teal-500/10 text-teal-400 border-teal-500/20',
  },
  {
    key: 'imageEdit',
    label: 'Edit',
    icon: Pencil,
    activeClass: 'bg-pink-500/10 text-pink-400 border-pink-500/20',
  },
]

export function ModelFilters({
  searchQuery,
  onSearchChange,
  providers,
  selectedProviders,
  onProviderToggle,
  capabilityFilters,
  onCapabilityToggle,
  sortBy,
  onSortChange,
  groupByProvider,
  onGroupByProviderToggle,
}: ModelFiltersProps) {
  return (
    <div className="space-y-4">
      {/* Search & Sort */}
      <div className="flex flex-col sm:flex-row gap-3">
        <div className="relative flex-1">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400" />
          <input
            type="text"
            placeholder="Search models by name or alias..."
            value={searchQuery}
            onChange={(e) => onSearchChange(e.target.value)}
            className="w-full pl-10 pr-4 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
          />
        </div>

        <select
          value={sortBy}
          onChange={(e) => onSortChange(e.target.value)}
          className="px-4 py-2 rounded-lg border border-slate-700 bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-amber-500/40 focus:border-amber-500"
        >
          {SORT_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </div>

      {/* Provider Filters */}
      <div>
        <div className="text-xs font-medium text-slate-400 mb-2">Providers</div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(providers).map(([id, displayName]) => {
            const isSelected = selectedProviders.has(id)
            const providerColor = PROVIDER_COLORS[id] ?? {
              dot: 'bg-slate-400',
              bg: 'border-slate-500/20',
            }
            return (
              <button
                key={id}
                type="button"
                onClick={() => onProviderToggle(id)}
                className={cn(
                  'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                  isSelected
                    ? cn(
                        'border-current',
                        providerColor.dot.replace('bg-', 'text-'),
                        providerColor.bg,
                      )
                    : 'border-slate-700 text-slate-400 hover:border-slate-600',
                )}
              >
                <div
                  className={cn(
                    'w-2 h-2 rounded-full',
                    isSelected ? providerColor.dot : 'bg-slate-600',
                  )}
                />
                <span>{displayName}</span>
              </button>
            )
          })}
        </div>
      </div>

      {/* Capability Filters */}
      <div>
        <div className="text-xs font-medium text-slate-400 mb-2">
          Capabilities
        </div>
        <div className="flex flex-wrap gap-2">
          {CAPABILITY_BUTTONS.map(({ key, label, icon: Icon, activeClass }) => (
            <button
              key={key}
              type="button"
              onClick={() => onCapabilityToggle(key)}
              className={cn(
                'flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-medium border transition-all',
                capabilityFilters[key]
                  ? activeClass
                  : 'border-slate-700 text-slate-400 hover:border-slate-600',
              )}
            >
              <Icon className="h-3 w-3" />
              <span>{label}</span>
            </button>
          ))}
        </div>
      </div>

      {/* Group by Provider Toggle */}
      <div className="flex items-center gap-2">
        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={groupByProvider}
            onChange={onGroupByProviderToggle}
            className="rounded border-slate-600 text-amber-500 focus:ring-amber-500"
          />
          <span className="text-xs font-medium text-slate-400">
            Group by Provider
          </span>
        </label>
      </div>
    </div>
  )
}
