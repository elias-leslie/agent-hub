import { User, Cpu, Sparkles, FileText, Volume2, Timer, Shield, Brain } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PersonaTabId } from "../types";

const TABS: { id: PersonaTabId; label: string; icon: React.ElementType }[] = [
  { id: "identity", label: "Identity", icon: User },
  { id: "models", label: "Models", icon: Cpu },
  { id: "personality", label: "Personality", icon: Sparkles },
  { id: "prompt", label: "Prompt", icon: FileText },
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
}

export function PersonaSettingsSidebar({
  activeTab,
  onTabChange,
  personaName,
  version,
  updatedAt,
}: PersonaSettingsSidebarProps) {
  return (
    <nav className="w-52 min-h-[calc(100vh-3.5rem)] border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-col">
      <div className="space-y-1 flex-1">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => onTabChange(tab.id)}
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
  );
}
