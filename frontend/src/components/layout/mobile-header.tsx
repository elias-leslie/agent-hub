import { Menu, Zap } from 'lucide-react'
import Link from 'next/link'

interface MobileHeaderProps {
  onMenuClick: () => void
}

export function MobileHeader({ onMenuClick }: MobileHeaderProps) {
  return (
    <header className="flex h-16 items-center justify-between border-b border-slate-800/70 bg-slate-950/75 px-4 backdrop-blur-xl lg:hidden">
      <button onClick={onMenuClick} className="icon-button -ml-1 h-11 w-11">
        <Menu className="h-5 w-5 text-slate-400" />
      </button>

      <Link href="/dashboard" className="flex items-center gap-2">
        <div className="rounded-xl border border-amber-400/20 bg-gradient-to-br from-amber-500 to-orange-600 p-2 shadow-[0_18px_38px_-28px_rgba(245,158,11,0.75)]">
          <Zap className="h-4 w-4 text-white" />
        </div>
        <div>
          <span className="block text-sm font-semibold text-slate-100">
            Agent Hub
          </span>
          <span className="block text-[10px] uppercase tracking-[0.22em] text-slate-500">
            Command Center
          </span>
        </div>
      </Link>

      {/* Placeholder for balance */}
      <div className="w-11" />
    </header>
  )
}
