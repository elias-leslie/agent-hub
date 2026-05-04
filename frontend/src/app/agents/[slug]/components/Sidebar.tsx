import {
  Brain,
  ChevronRight,
  Cpu,
  Network,
  ScrollText,
  Settings2,
  Sliders,
  X,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import type { Agent, TabId } from '../types'

const ALL_TABS: {
  id: TabId
  label: string
  description: string
  icon: React.ElementType
}[] = [
  {
    id: 'general',
    label: 'General',
    description: 'Name, state, and execution role.',
    icon: Settings2,
  },
  {
    id: 'models',
    label: 'Models',
    description: 'Primary, fallback, and escalation routing.',
    icon: Cpu,
  },
  {
    id: 'parameters',
    label: 'Parameters',
    description: 'Reasoning depth, temperature, and limits.',
    icon: Sliders,
  },
  {
    id: 'prompts',
    label: 'Prompts',
    description: 'Prompt stack ordering, docs, and preview.',
    icon: ScrollText,
  },
  {
    id: 'memory',
    label: 'Memory',
    description: 'Memory inheritance, filters, and retrieval.',
    icon: Brain,
  },
  {
    id: 'committee',
    label: 'Committee',
    description: 'Seat roster, model overrides, and validation run.',
    icon: Network,
  },
]

export function getAgentEditorTabs(agentSlug: string): typeof ALL_TABS {
  if (agentSlug === 'investment-committee') return ALL_TABS
  return ALL_TABS.filter((tab) => tab.id !== 'committee')
}

export { ALL_TABS as AGENT_EDITOR_TABS }

interface SidebarProps {
  activeTab: TabId
  agent: Agent
  onTabChange: (tab: TabId) => void
  mobileOpen?: boolean
  onMobileClose?: () => void
}

export function Sidebar({
  activeTab,
  agent,
  onTabChange,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const handleTabClick = (tab: TabId) => {
    onTabChange(tab)
    onMobileClose?.()
  }

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onMobileClose}
          onKeyDown={(e) => {
            if (e.key === 'Escape') onMobileClose?.()
          }}
        />
      )}

      <nav
        className={cn(
          'panel-surface w-full p-4 lg:w-[18.5rem] lg:self-start',
          'lg:relative lg:translate-x-0 lg:z-auto',
          'max-lg:fixed max-lg:top-20 max-lg:left-4 max-lg:bottom-4 max-lg:z-40 max-lg:w-[min(21rem,calc(100vw-2rem))] max-lg:shadow-2xl',
          'max-lg:transition-transform max-lg:duration-200 max-lg:ease-in-out',
          mobileOpen ? 'max-lg:translate-x-0' : 'max-lg:-translate-x-full',
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="section-kicker">Editor Map</p>
            <div>
              <h2 className="text-sm font-semibold text-slate-100">
                Agent Surface
              </h2>
              <p className="text-xs text-slate-400">
                Move through the runtime configuration in order.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onMobileClose}
            aria-label="Close editor sections"
            className="icon-button h-9 w-9 lg:hidden"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-2">
          {getAgentEditorTabs(agent.slug).map((tab) => (
            <button
              key={tab.id}
              type="button"
              aria-label={tab.label}
              onClick={() => handleTabClick(tab.id)}
              className={cn(
                'group w-full rounded-2xl border px-3 py-3 text-left transition',
                activeTab === tab.id
                  ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
                  : 'border-transparent bg-slate-950/25 text-slate-300 hover:border-slate-700/80 hover:bg-slate-950/70',
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    'mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl border transition',
                    activeTab === tab.id
                      ? 'border-amber-400/25 bg-amber-500/10 text-amber-200'
                      : 'border-slate-800 bg-slate-900/90 text-slate-400 group-hover:border-slate-700 group-hover:text-slate-200',
                  )}
                >
                  <tab.icon className="h-4 w-4" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{tab.label}</span>
                    <ChevronRight
                      className={cn(
                        'h-4 w-4 transition',
                        activeTab === tab.id
                          ? 'text-amber-300'
                          : 'text-slate-600 group-hover:text-slate-400',
                      )}
                    />
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500 group-hover:text-slate-400">
                    {tab.description}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>

        <div className="mt-5 rounded-2xl border border-slate-800/80 bg-slate-950/60 p-4">
          <p className="section-kicker">Snapshot</p>
          <div className="mt-3 space-y-3">
            <div className="detail-card p-3">
              <p className="detail-label">Version</p>
              <p className="detail-value font-mono">v{agent.version}</p>
            </div>
            <div className="detail-card p-3">
              <p className="detail-label">Updated</p>
              <p className="detail-value">
                {new Date(agent.updated_at).toLocaleDateString(undefined, {
                  month: 'short',
                  day: 'numeric',
                  year: 'numeric',
                })}
              </p>
            </div>
          </div>
        </div>
      </nav>
    </>
  )
}
