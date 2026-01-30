import { Settings2, Cpu, FileText, Sliders } from "lucide-react";
import { cn } from "@/lib/utils";
import { TabId, Agent } from "../types";

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: Settings2 },
  { id: "models", label: "Models", icon: Cpu },
  { id: "prompt", label: "Prompt", icon: FileText },
  { id: "parameters", label: "Parameters", icon: Sliders },
];

interface SidebarProps {
  activeTab: TabId;
  agent: Agent;
  onTabChange: (tab: TabId) => void;
}

export function Sidebar({ activeTab, agent, onTabChange }: SidebarProps) {
  return (
    <nav className="w-48 min-h-[calc(100vh-3.5rem)] border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <div className="space-y-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
            className={cn(
              "flex items-center gap-2 w-full px-3 py-2 rounded-lg text-sm font-medium transition-colors",
              activeTab === tab.id
                ? "bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400"
                : "text-slate-600 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800"
            )}
          >
            <tab.icon className="h-4 w-4" />
            {tab.label}
          </button>
        ))}
      </div>

      <div className="mt-8 pt-4 border-t border-slate-200 dark:border-slate-700">
        <p className="text-[10px] text-slate-400 uppercase tracking-wider mb-2">
          Version
        </p>
        <p className="text-sm font-mono text-slate-600 dark:text-slate-300">
          v{agent.version}
        </p>
        <p className="text-[10px] text-slate-400 mt-1">
          Updated {new Date(agent.updated_at).toLocaleDateString()}
        </p>
      </div>
    </nav>
  );
}
