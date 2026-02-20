"use client";

import { useState, useEffect } from "react";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { fetchStatus } from "@/lib/api";
import { SettingsModal } from "@/components/settings-modal";
import { SidebarLogo } from "./sidebar-logo";
import { SidebarNav } from "./sidebar-nav";
import { SidebarFooter } from "./sidebar-footer";
import { MobileHeader } from "./mobile-header";

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);

  // Fetch system status for the indicator
  const { data: status } = useQuery({
    queryKey: ["status"],
    queryFn: fetchStatus,
    refetchInterval: 30000,
    staleTime: 10000,
  });

  // Close mobile nav on route change
  useEffect(() => {
    setIsMobileOpen(false);
  }, [pathname]);

  // Don't show shell on landing page
  if (pathname === "/") {
    return <>{children}</>;
  }

  return (
    <div className="flex h-screen bg-slate-50 dark:bg-slate-950">
      {/* Mobile overlay */}
      {isMobileOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 backdrop-blur-sm lg:hidden"
          onClick={() => setIsMobileOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={cn(
          "fixed lg:static inset-y-0 left-0 z-50",
          "flex flex-col",
          "bg-white dark:bg-slate-900",
          "border-r border-slate-200 dark:border-slate-800",
          "sidebar-transition",
          // Desktop width
          isCollapsed ? "lg:w-14" : "lg:w-48",
          // Mobile
          isMobileOpen
            ? "translate-x-0 w-[280px]"
            : "-translate-x-full lg:translate-x-0",
        )}
      >
        <SidebarLogo
          isCollapsed={isCollapsed}
          isMobileOpen={isMobileOpen}
          statusIndicator={status?.status}
          onMobileClose={() => setIsMobileOpen(false)}
        />

        <SidebarNav isCollapsed={isCollapsed} pathname={pathname} />

        <SidebarFooter
          isCollapsed={isCollapsed}
          status={status}
          onSettingsClick={() => setIsSettingsOpen(true)}
          onCollapseToggle={() => setIsCollapsed(!isCollapsed)}
        />
      </aside>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <MobileHeader onMenuClick={() => setIsMobileOpen(true)} />

        {/* Page content */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>

      {/* Settings Modal */}
      <SettingsModal
        isOpen={isSettingsOpen}
        onClose={() => setIsSettingsOpen(false)}
      />
    </div>
  );
}
