import { User, Cpu, ScrollText, Volume2, Timer, Shield, Brain, X } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PersonaTabId } from "../types";

const TABS: { id: PersonaTabId; label: string; icon: React.ElementType }[] = [
  { id: "identity", label: "Identity", icon: User },
  { id: "models", label: "Models", icon: Cpu },
  { id: "prompts", label: "Prompts", icon: ScrollText },
  { id: "voice", label: "Voice & Heartbeat", icon: Volume2 },
  { id: "session", label: "Session & Limits", icon: Timer },
  { id: "permissions", label: "Permissions", icon: Shield },
  { id: "memory", label: "Memory", icon: Brain },
];

interface PersonaSettingsSidebarProps {
  activeTab: PersonaTabId;
  onTabChange: (tab: PersonaTabId) => void;
  personaName?: string;
  version?: number;
  updatedAt?: string | null;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export { TABS as PERSONA_SETTINGS_TABS };

export function PersonaSettingsSidebar({
  activeTab,
  onTabChange,
  personaName,
  version,
  updatedAt,
  mobileOpen,
  onMobileClose,
}: PersonaSettingsSidebarProps) {
  const handleTabClick = (tabId: PersonaTabId) => {
    onTabChange(tabId);
    onMobileClose?.();
  };

  return (
    <>
      {/* Mobile overlay backdrop */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onMobileClose}
          onKeyDown={(e) => {
            if (e.key === "Escape") onMobileClose?.();
          }}
        />
      )}

      {/* Sidebar */}
      <nav
        className={cn(
          // Desktop: static sidebar
          "lg:relative lg:translate-x-0 lg:z-auto",
          "w-52 min-h-[calc(100vh-3.5rem)] border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-col",
          // Mobile: fixed overlay sidebar
          "max-lg:fixed max-lg:top-14 max-lg:left-0 max-lg:bottom-0 max-lg:z-40 max-lg:shadow-xl",
          "max-lg:transition-transform max-lg:duration-200 max-lg:ease-in-out",
          mobileOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full",
        )}
      >
        {/* Mobile close button */}
        <div className="flex items-center justify-between mb-2 lg:hidden">
          <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
            Settings
          </span>
          <button
            type="button"
            onClick={onMobileClose}
            className="p-1 rounded-md text-slate-500 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-1 flex-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabClick(tab.id)}
              className={cn(
                "flex items-center gap-2.5 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                activeTab === tab.id
                  ? "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400"
                  : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800",
              )}
            >
              <tab.icon className="h-4 w-4 flex-shrink-0" />
              {tab.label}
            </button>
          ))}
        </div>

        {(personaName || version != null) && (
          <div className="pt-4 border-t border-slate-200 dark:border-slate-700">
            {personaName && (
              <p className="text-sm font-medium text-slate-700 dark:text-slate-300 truncate">
                {personaName}
              </p>
            )}
            {version != null && (
              <p className="text-xs font-mono text-slate-400 mt-0.5">
                v{version}
              </p>
            )}
            {updatedAt && (
              <p className="text-[10px] text-slate-400 mt-0.5">
                Updated {new Date(updatedAt).toLocaleDateString()}
              </p>
            )}
          </div>
        )}
      </nav>
    </>
  );
}
