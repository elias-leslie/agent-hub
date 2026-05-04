'use client'

import { BarChart3, List, MonitorDot, Radio } from 'lucide-react'
import { cn } from '@/lib/utils'

const TABS = [
  { id: 'episodes', label: 'Episodes', icon: List },
  { id: 'sessions', label: 'Sessions', icon: MonitorDot },
  { id: 'capture', label: 'Capture', icon: Radio },
  { id: 'analytics', label: 'Analytics', icon: BarChart3 },
] as const

export type MemoryTabId = (typeof TABS)[number]['id']

interface MemoryTabsProps {
  activeTab: MemoryTabId
  onTabChange: (tab: MemoryTabId) => void
}

export function MemoryTabs({ activeTab, onTabChange }: MemoryTabsProps) {
  return (
    <div className="flex items-center gap-1 px-6 lg:px-8 border-b border-slate-800/60 bg-slate-900/60 overflow-x-auto">
      {TABS.map((tab) => {
        const Icon = tab.icon
        const isActive = activeTab === tab.id
        return (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              'flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition-colors whitespace-nowrap',
              isActive
                ? 'border-emerald-500 text-emerald-400'
                : 'border-transparent text-slate-400 hover:text-slate-200',
            )}
          >
            <Icon className="h-4 w-4" />
            {tab.label}
          </button>
        )
      })}
    </div>
  )
}
