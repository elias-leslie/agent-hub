"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  MessageSquare,
  History,
  Settings,
  ChevronLeft,
  ChevronRight,
  Zap,
  Activity,
  Menu,
  X,
  Brain,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useQuery } from "@tanstack/react-query";
import { fetchStatus } from "@/lib/api";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  description: string;
}

const NAV_ITEMS: NavItem[] = [
  {
    href: "/dashboard",
    label: "Dashboard",
    icon: LayoutDashboard,
    description: "Monitoring & analytics",
  },
  {
    href: "/chat",
    label: "Chat",
    icon: MessageSquare,
    description: "Test & interact",
  },
  {
    href: "/sessions",
    label: "Sessions",
    icon: History,
    description: "History & logs",
  },
  {
    href: "/memory",
    label: "Memory",
    icon: Brain,
    description: "Knowledge graph",
  },
  {
    href: "/settings",
    label: "Settings",
    icon: Settings,
    description: "Configuration",
  },
];

interface AppShellProps {
  children: React.ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const pathname = usePathname();
  const [isCollapsed, setIsCollapsed] = useState(false);
  const [isMobileOpen, setIsMobileOpen] = useState(false);

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

  const isActive = (href: string) => {
    if (href === "/dashboard") return pathname === "/dashboard";
    return pathname.startsWith(href);
  };

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
          isCollapsed ? "lg:w-[72px]" : "lg:w-[240px]",
          // Mobile
          isMobileOpen
            ? "translate-x-0 w-[280px]"
            : "-translate-x-full lg:translate-x-0",
        )}
      >
        {/* Logo Header */}
        <div className="flex items-center justify-between h-16 px-4 border-b border-slate-200 dark:border-slate-800">
          <Link
            href="/"
            className={cn(
              "flex items-center gap-3",
              isCollapsed && "lg:justify-center",
            )}
          >
            <div className="relative flex-shrink-0">
              <div className="p-2 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 shadow-lg glow-amber">
                <Zap className="h-5 w-5 text-white" />
              </div>
              {/* Status indicator */}
              <div
                className={cn(
                  "absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border-2 border-white dark:border-slate-900",
                  status?.status === "healthy"
                    ? "bg-emerald-500 animate-status-pulse"
                    : status?.status === "degraded"
                      ? "bg-amber-500"
                      : "bg-slate-400",
                )}
              />
            </div>
            {!isCollapsed && (
              <div className="lg:block hidden">
                <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
                  Agent Hub
                </h1>
                <p className="text-[10px] font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
                  Command Center
                </p>
              </div>
            )}
            {/* Mobile always shows title */}
            <div className="lg:hidden">
              <h1 className="text-base font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
                Agent Hub
              </h1>
            </div>
          </Link>

          {/* Mobile close */}
          <button
            onClick={() => setIsMobileOpen(false)}
            className="p-2 lg:hidden rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5 text-slate-500" />
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
          {NAV_ITEMS.map((item) => {
            const active = isActive(item.href);
            const Icon = item.icon;

            return (
              <Link
                key={item.href}
                href={item.href}
                data-active={active}
                className={cn(
                  "nav-item-hover flex items-center gap-3 px-3 py-2.5 rounded-lg",
                  "transition-colors duration-150",
                  "focus-ring-amber",
                  active
                    ? "bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-400"
                    : "text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 hover:text-slate-900 dark:hover:text-slate-200",
                  isCollapsed && "lg:justify-center lg:px-0",
                )}
                title={isCollapsed ? item.label : undefined}
              >
                <Icon
                  className={cn(
                    "h-5 w-5 flex-shrink-0",
                    active && "text-amber-600 dark:text-amber-400",
                  )}
                />
                {!isCollapsed && (
                  <div className="lg:block hidden">
                    <span className="text-sm font-medium">{item.label}</span>
                    <p className="text-[10px] text-slate-400 dark:text-slate-500">
                      {item.description}
                    </p>
                  </div>
                )}
                {/* Mobile always shows labels */}
                <div className="lg:hidden">
                  <span className="text-sm font-medium">{item.label}</span>
                  <p className="text-[10px] text-slate-400 dark:text-slate-500">
                    {item.description}
                  </p>
                </div>
              </Link>
            );
          })}
        </nav>

        {/* Footer with collapse toggle */}
        <div className="p-3 border-t border-slate-200 dark:border-slate-800">
          {/* System status summary */}
          {!isCollapsed && status && (
            <div className="hidden lg:flex items-center gap-2 px-3 py-2 mb-2 rounded-lg bg-slate-50 dark:bg-slate-800/50">
              <Activity
                className={cn(
                  "h-4 w-4",
                  status.status === "healthy"
                    ? "text-emerald-500"
                    : "text-amber-500",
                )}
              />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-slate-700 dark:text-slate-300 capitalize">
                  {status.status}
                </p>
                <p className="text-[10px] text-slate-500 dark:text-slate-400 font-mono">
                  {Math.floor(status.uptime_seconds / 3600)}h uptime
                </p>
              </div>
            </div>
          )}

          {/* Collapse toggle - desktop only */}
          <button
            onClick={() => setIsCollapsed(!isCollapsed)}
            className={cn(
              "hidden lg:flex items-center gap-2 w-full px-3 py-2 rounded-lg",
              "text-slate-500 dark:text-slate-400",
              "hover:bg-slate-100 dark:hover:bg-slate-800",
              "transition-colors duration-150",
              isCollapsed && "justify-center",
            )}
          >
            {isCollapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <>
                <ChevronLeft className="h-4 w-4" />
                <span className="text-xs">Collapse</span>
              </>
            )}
          </button>
        </div>
      </aside>

      {/* Main content area */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Mobile header */}
        <header className="lg:hidden flex items-center justify-between h-14 px-4 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          <button
            onClick={() => setIsMobileOpen(true)}
            className="p-2 -ml-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <Menu className="h-5 w-5 text-slate-600 dark:text-slate-400" />
          </button>

          <Link href="/" className="flex items-center gap-2">
            <div className="p-1.5 rounded-md bg-gradient-to-br from-amber-500 to-orange-600">
              <Zap className="h-4 w-4 text-white" />
            </div>
            <span className="text-sm font-semibold text-slate-900 dark:text-slate-100">
              Agent Hub
            </span>
          </Link>

          {/* Placeholder for balance */}
          <div className="w-9" />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-auto">{children}</main>
      </div>
    </div>
  );
}
