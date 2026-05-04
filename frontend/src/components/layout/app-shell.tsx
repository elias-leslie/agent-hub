'use client'

import { useQuery } from '@tanstack/react-query'
import { usePathname } from 'next/navigation'
import { useEffect, useState } from 'react'
import { usePersonaDisplayName } from '@/app/persona/hooks/usePersonaDisplayName'
import { SettingsModal } from '@/components/settings-modal'
import { fetchStatus } from '@/lib/api'
import { cn } from '@/lib/utils'
import { MobileHeader } from './mobile-header'
import { SidebarFooter } from './sidebar-footer'
import { SidebarLogo } from './sidebar-logo'
import { SidebarNav } from './sidebar-nav'

interface AppShellProps {
  children: React.ReactNode
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname()
  const [isCollapsed, setIsCollapsed] = useState(false)
  const [isMobileOpen, setIsMobileOpen] = useState(false)
  const [isSettingsOpen, setIsSettingsOpen] = useState(false)

  // Fetch system status for the indicator
  const { data: status } = useQuery({
    queryKey: ['status'],
    queryFn: fetchStatus,
    refetchInterval: 30000,
    staleTime: 10000,
  })
  const { personaName } = usePersonaDisplayName()

  // Close mobile nav on route change
  useEffect(() => {
    setIsMobileOpen(false)
  }, [pathname])

  return (
    <div className="relative flex h-screen overflow-hidden bg-transparent">
      <div className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(245,158,11,0.08),transparent_24%),radial-gradient(circle_at_top_right,rgba(56,189,248,0.06),transparent_22%)]" />
      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-950/70 backdrop-blur-sm lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed lg:static inset-y-0 left-0 z-50',
          'flex flex-col',
          'bg-slate-950/80 backdrop-blur-xl',
          'border-r border-slate-800/70',
          'shadow-[0_30px_80px_-55px_rgba(0,0,0,0.95)]',
          'sidebar-transition',
          // Desktop width
          isCollapsed ? 'lg:w-18' : 'lg:w-60',
          // Mobile
          isMobileOpen
            ? 'translate-x-0 w-[280px]'
            : '-translate-x-full lg:translate-x-0',
        )}
      >
        <SidebarLogo
          isCollapsed={isCollapsed}
          isMobileOpen={isMobileOpen}
          statusIndicator={status?.status}
          onMobileClose={() => setIsMobileOpen(false)}
        />

        <SidebarNav
          isCollapsed={isCollapsed}
          pathname={pathname}
          personaName={personaName}
        />

        <SidebarFooter
          isCollapsed={isCollapsed}
          status={status}
          onSettingsClick={() => setIsSettingsOpen(true)}
          onCollapseToggle={() => setIsCollapsed(!isCollapsed)}
        />
      </aside>

      {/* Main content area */}
      <div className="relative flex min-w-0 flex-1 flex-col overflow-hidden">
        <MobileHeader onMenuClick={() => setIsMobileOpen(true)} />

        {/* Page content */}
        <main className="relative flex-1 overflow-auto">{children}</main>
      </div>

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  )
}
