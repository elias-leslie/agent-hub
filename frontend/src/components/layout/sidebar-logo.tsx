import Link from "next/link";
import { Zap, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface SidebarLogoProps {
  isCollapsed: boolean;
  isMobileOpen: boolean;
  statusIndicator?: "healthy" | "degraded" | "unknown";
  onMobileClose: () => void;
}

export function SidebarLogo({
  isCollapsed,
  isMobileOpen,
  statusIndicator = "unknown",
  onMobileClose,
}: SidebarLogoProps) {
  return (
    <div className="flex items-center justify-between h-14 px-3 border-b border-slate-200 dark:border-slate-800">
      <Link
        href="/"
        className={cn(
          "flex items-center gap-2.5",
          isCollapsed && "lg:justify-center",
        )}
      >
        <div className="relative flex-shrink-0">
          <div className="p-1.5 rounded-lg bg-gradient-to-br from-amber-500 to-orange-600 shadow-lg glow-amber">
            <Zap className="h-4 w-4 text-white" />
          </div>
          {/* Status indicator */}
          <div
            className={cn(
              "absolute -bottom-0.5 -right-0.5 h-2.5 w-2.5 rounded-full border-2 border-white dark:border-slate-900",
              statusIndicator === "healthy"
                ? "bg-emerald-500 animate-status-pulse"
                : statusIndicator === "degraded"
                  ? "bg-amber-500"
                  : "bg-slate-400",
            )}
          />
        </div>
        {!isCollapsed && (
          <div className="lg:block hidden">
            <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100 tracking-tight leading-tight">
              Agent Hub
            </h1>
            <p className="text-[9px] font-medium text-slate-500 dark:text-slate-400 uppercase tracking-wider">
              Command Center
            </p>
          </div>
        )}
        {/* Mobile always shows title */}
        <div className="lg:hidden">
          <h1 className="text-sm font-semibold text-slate-900 dark:text-slate-100 tracking-tight">
            Agent Hub
          </h1>
        </div>
      </Link>

      {/* Mobile close */}
      <button
        onClick={onMobileClose}
        className="p-2 lg:hidden rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <X className="h-5 w-5 text-slate-500" />
      </button>
    </div>
  );
}
