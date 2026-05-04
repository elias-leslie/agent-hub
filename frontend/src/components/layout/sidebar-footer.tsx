import { NotesButton, NotesProvider } from '@summitflow/notes-ui'
import { Activity, ChevronLeft, ChevronRight, Settings } from 'lucide-react'
import { cn } from '@/lib/utils'

interface StatusData {
  status: 'healthy' | 'degraded' | 'unknown'
  uptime_seconds: number
}

interface SidebarFooterProps {
  isCollapsed: boolean
  status?: StatusData
  onSettingsClick: () => void
  onCollapseToggle: () => void
}

export function SidebarFooter({
  isCollapsed,
  status,
  onSettingsClick,
  onCollapseToggle,
}: SidebarFooterProps) {
  return (
    <div className="border-t border-slate-800/70 bg-slate-950/30 px-3 py-3">
      {/* System status summary */}
      {!isCollapsed && status && (
        <div className="mb-2 hidden items-center gap-3 rounded-2xl border border-slate-800/70 bg-slate-900/75 px-3 py-2.5 lg:flex">
          <Activity
            className={cn(
              'h-4 w-4 flex-shrink-0',
              status.status === 'healthy'
                ? 'text-emerald-500'
                : 'text-amber-500',
            )}
          />
          <div className="flex-1 min-w-0">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-300">
              {status.status}
            </p>
            <p className="text-[10px] text-slate-500 font-mono">
              {Math.floor(status.uptime_seconds / 3600)}h uptime
            </p>
          </div>
        </div>
      )}

      <div
        className={cn(
          'mb-1 flex w-full items-center gap-2 rounded-xl px-1.5 py-1',
          isCollapsed && 'justify-center',
        )}
      >
        <NotesProvider apiPrefix="/api" projectScope="agent-hub">
          <NotesButton popOutUrl="/notes" />
        </NotesProvider>
        {!isCollapsed && (
          <span className="text-[13px] text-slate-400 hidden lg:block">
            Notes
          </span>
        )}
        <span className="text-[13px] text-slate-400 lg:hidden">Notes</span>
      </div>

      {/* Settings button */}
      <button
        onClick={onSettingsClick}
        className={cn(
          'mb-1 flex w-full items-center gap-2 rounded-xl px-3 py-2',
          'text-slate-400',
          'border border-transparent hover:border-slate-700/70 hover:bg-slate-800/80',
          'transition-colors duration-150',
          isCollapsed && 'justify-center',
        )}
        title={isCollapsed ? 'Settings' : undefined}
        aria-label="Settings"
      >
        <Settings className="h-3.5 w-3.5" />
        {!isCollapsed && (
          <span className="text-[13px] hidden lg:block">Settings</span>
        )}
        {/* Mobile always shows label */}
        <span className="text-[13px] lg:hidden">Settings</span>
      </button>

      {/* Collapse toggle - desktop only */}
      <button
        onClick={onCollapseToggle}
        className={cn(
          'hidden w-full items-center gap-2 rounded-xl px-3 py-2 lg:flex',
          'text-slate-400',
          'border border-transparent hover:border-slate-700/70 hover:bg-slate-800/80',
          'transition-colors duration-150',
          isCollapsed && 'justify-center',
        )}
        aria-label={isCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
      >
        {isCollapsed ? (
          <ChevronRight className="h-3.5 w-3.5" />
        ) : (
          <>
            <ChevronLeft className="h-3.5 w-3.5" />
            <span className="text-[13px]">Collapse</span>
          </>
        )}
      </button>
    </div>
  )
}
