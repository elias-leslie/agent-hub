import { Settings2, Cpu, FileText, Sliders, Shield, ScrollText, Brain, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { TabId, Agent } from "../types";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: Settings2 },
  { id: "models", label: "Models", icon: Cpu },
  { id: "parameters", label: "Parameters", icon: Sliders },
  { id: "permissions", label: "Permissions", icon: Shield },
  { id: "prompts", label: "Prompts", icon: ScrollText },
  { id: "memory", label: "Memory", icon: Brain },
];

export { TABS as AGENT_EDITOR_TABS };

interface SidebarProps {
  activeTab: TabId;
  agent: Agent;
  onTabChange: (tab: TabId) => void;
  mobileOpen?: boolean;
  onMobileClose?: () => void;
}

export function Sidebar({
  activeTab,
  agent,
  onTabChange,
  mobileOpen,
  onMobileClose,
}: SidebarProps) {
  const handleTabClick = (tab: TabId) => {
    onTabChange(tab);
    onMobileClose?.();
  };

  return (
    <>
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
          onClick={onMobileClose}
          onKeyDown={(e) => {
            if (e.key === "Escape") onMobileClose?.();
          }}
        />
      )}

      <nav
        className={cn(
          "w-48 min-h-[calc(100vh-3.5rem)] border-r border-slate-800 bg-slate-900 p-4",
          "lg:relative lg:translate-x-0 lg:z-auto",
          "max-lg:fixed max-lg:top-14 max-lg:left-0 max-lg:bottom-0 max-lg:z-40 max-lg:shadow-xl",
          "max-lg:transition-transform max-lg:duration-200 max-lg:ease-in-out",
          mobileOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full",
        )}
      >
        <div className="mb-2 flex items-center justify-between lg:hidden">
          <span className="text-sm font-semibold text-slate-300">
            Sections
          </span>
          <button
            type="button"
            onClick={onMobileClose}
            aria-label="Close editor sections"
            className="rounded-md p-1 text-slate-500 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabClick(tab.id)}
              className={cn(
                "flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors",
                activeTab === tab.id
                  ? "bg-amber-950/40 text-amber-500 dark:text-amber-400"
                  : "text-slate-400 hover:bg-slate-800"
              )}
            >
              <tab.icon className="h-4 w-4" />
              {tab.label}
            </button>
          ))}
        </div>

        <div className="mt-8 border-t border-slate-200 pt-4 dark:border-slate-700">
          <p className="mb-2 text-[10px] uppercase tracking-wider text-slate-400">
            Version
          </p>
          <p className="text-sm font-mono text-slate-300">
            v{agent.version}
          </p>
          <p className="mt-1 text-[10px] text-slate-400">
            Updated {new Date(agent.updated_at).toLocaleDateString()}
          </p>
        </div>
      </nav>
    </>
  );
}
