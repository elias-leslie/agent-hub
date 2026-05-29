import {
  ArrowLeft,
  Bot,
  Eye,
  Loader2,
  Menu,
  MessageSquare,
  Save,
} from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { cn } from '@/lib/utils'
import type { Agent } from '../types'

interface AgentEditorHeaderProps {
  agent: Agent
  hasChanges: boolean
  isSaving: boolean
  onSave: () => void
  onPreview: () => void
  onOpenSidebar?: () => void
  activeTabLabel?: string
}

export function AgentEditorHeader({
  agent,
  hasChanges,
  isSaving,
  onSave,
  onPreview,
  onOpenSidebar,
  activeTabLabel,
}: AgentEditorHeaderProps) {
  const router = useRouter()

  return (
    <header className="page-header">
      <div className="page-container px-4 lg:px-8">
        <div className="page-header-row">
          <div className="page-title-group">
            <button
              type="button"
              onClick={onOpenSidebar}
              aria-label="Open editor sections"
              className="icon-button lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => router.push('/agents')}
              aria-label="Back to agents"
              className="icon-button"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <div className="page-title-icon">
              <Bot className="h-5 w-5" />
            </div>
            <div className="page-title-stack">
              <div className="flex flex-wrap items-center gap-2">
                <h1 className="page-title">{agent.name}</h1>
                <span className="page-pill font-mono">{agent.slug}</span>
                {activeTabLabel && (
                  <span className="page-pill lg:hidden">{activeTabLabel}</span>
                )}
              </div>
              <div className="page-meta">
                <span className="page-pill">v{agent.version}</span>
                <span
                  className={cn(
                    'page-pill',
                    agent.is_active
                      ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200'
                      : 'border-slate-700/80 bg-slate-900/90 text-slate-400',
                  )}
                >
                  {agent.is_active ? 'Active' : 'Inactive'}
                </span>
                <span
                  className={cn(
                    'page-pill',
                    hasChanges
                      ? 'border-amber-500/20 bg-amber-500/10 text-amber-100'
                      : 'border-slate-700/80 bg-slate-900/90 text-slate-400',
                  )}
                >
                  {hasChanges ? 'Unsaved changes' : 'Saved'}
                </span>
              </div>
            </div>
          </div>

          <div className="page-toolbar">
            <button
              type="button"
              onClick={onPreview}
              className="button-secondary"
            >
              <Eye className="h-4 w-4" />
              Preview
            </button>
            <Link
              href={`/agents/${agent.slug}/chat`}
              className="button-secondary"
            >
              <MessageSquare className="h-4 w-4" />
              Chat
            </Link>
            <button
              type="button"
              onClick={onSave}
              disabled={!hasChanges || isSaving}
              className="button-primary disabled:cursor-not-allowed disabled:border-slate-700 disabled:bg-slate-800 disabled:text-slate-500 disabled:shadow-none"
            >
              {isSaving ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <Save className="h-4 w-4" />
              )}
              {isSaving ? 'Saving' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </header>
  )
}
