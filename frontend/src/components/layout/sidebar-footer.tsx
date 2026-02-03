import { Settings, Activity, ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusData {
  status: "healthy" | "degraded" | "unknown";
  uptime_seconds: number;
}

interface SidebarFooterProps {
  isCollapsed: boolean;
  status?: StatusData;
  onSettingsClick: () => void;
  onCollapseToggle: () => void;
}

export function SidebarFooter({
  isCollapsed,
  status,
  onSettingsClick,
  onCollapseToggle,
}: SidebarFooterProps) {
  return (
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

      {/* Settings button */}
      <button
        onClick={onSettingsClick}
        className={cn(
          "flex items-center gap-2 w-full px-3 py-2 mb-1 rounded-lg",
          "text-slate-500 dark:text-slate-400",
          "hover:bg-slate-100 dark:hover:bg-slate-800",
          "transition-colors duration-150",
          isCollapsed && "justify-center",
        )}
        title={isCollapsed ? "Settings" : undefined}
      >
        <Settings className="h-4 w-4" />
        {!isCollapsed && <span className="text-xs hidden lg:block">Settings</span>}
        {/* Mobile always shows label */}
        <span className="text-xs lg:hidden">Settings</span>
      </button>

      {/* Collapse toggle - desktop only */}
      <button
        onClick={onCollapseToggle}
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
  );
}
