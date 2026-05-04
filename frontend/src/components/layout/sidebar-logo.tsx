import { X, Zap } from 'lucide-react'
import Link from 'next/link'
import { cn } from '@/lib/utils'

interface SidebarLogoProps {
  isCollapsed: boolean
  isMobileOpen: boolean
  statusIndicator?: 'healthy' | 'degraded' | 'unknown'
  onMobileClose: () => void
}

export function SidebarLogo({
  isCollapsed,
  statusIndicator = 'unknown',
  onMobileClose,
}: SidebarLogoProps) {
  return (
    <div className="flex items-center justify-between border-b border-slate-800/70 px-3 py-3">
      <Link
        href="/dashboard"
        className={cn(
          'flex items-center gap-3',
          isCollapsed && 'lg:justify-center',
        )}
      >
        <div className="relative flex-shrink-0">
          <div className="rounded-2xl border border-amber-400/20 bg-gradient-to-br from-amber-500 to-orange-600 p-2 shadow-[0_18px_38px_-28px_rgba(245,158,11,0.8)]">
            <Zap className="h-4 w-4 text-white" />
          </div>
          {/* Status indicator */}
          <div
            className={cn(
              'absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-slate-900',
              statusIndicator === 'healthy'
                ? 'bg-emerald-500 animate-status-pulse'
                : statusIndicator === 'degraded'
                  ? 'bg-amber-500'
                  : 'bg-slate-400',
            )}
          />
        </div>
        {!isCollapsed && (
          <div className="lg:block hidden">
            <h1 className="text-sm font-semibold text-slate-100 tracking-tight leading-tight">
              Agent Hub
            </h1>
            <p className="text-[10px] font-medium text-slate-500 uppercase tracking-[0.24em]">
              Command Center
            </p>
          </div>
        )}
        {/* Mobile always shows title */}
        <div className="lg:hidden">
          <h1 className="text-sm font-semibold text-slate-100 tracking-tight">
            Agent Hub
          </h1>
        </div>
      </Link>

      {/* Mobile close */}
      <button
        onClick={onMobileClose}
        className="rounded-xl border border-slate-800 bg-slate-900/70 p-2 text-slate-400 transition hover:border-slate-700 hover:bg-slate-800/70 lg:hidden"
      >
        <X className="h-5 w-5" />
      </button>
    </div>
  )
}
