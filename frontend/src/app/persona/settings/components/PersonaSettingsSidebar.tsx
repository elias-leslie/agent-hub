import { User, Cpu, ScrollText, Volume2, Timer, Brain, X, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import type { PersonaTabId } from "../types";
import { getPersonaDisplayName } from "../../utils/displayName";

const TABS: { id: PersonaTabId; label: string; description: string; icon: React.ElementType }[] = [
  { id: "identity", label: "Identity", description: "Persona name, profile, and onboarding state.", icon: User },
  { id: "models", label: "Models", description: "Provider routing and generation defaults.", icon: Cpu },
  { id: "prompts", label: "Prompts", description: "Prompt stack, workflow docs, and previews.", icon: ScrollText },
  { id: "voice", label: "Voice & Heartbeat", description: "Speech preferences and heartbeat readiness.", icon: Volume2 },
  { id: "session", label: "Session & Limits", description: "Reset policy and execution ceilings.", icon: Timer },
  { id: "memory", label: "Memory", description: "Memory inheritance and audience filters.", icon: Brain },
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
  const displayName = getPersonaDisplayName(personaName);

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
          "lg:relative lg:translate-x-0 lg:z-auto",
          "panel-surface flex w-full flex-col p-4 lg:w-[19rem] lg:self-start",
          "max-lg:fixed max-lg:top-20 max-lg:left-4 max-lg:bottom-4 max-lg:z-40 max-lg:w-[min(21rem,calc(100vw-2rem))] max-lg:shadow-2xl",
          "max-lg:transition-transform max-lg:duration-200 max-lg:ease-in-out",
          mobileOpen ? "max-lg:translate-x-0" : "max-lg:-translate-x-full",
        )}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div className="space-y-1">
            <p className="section-kicker">Persona Workbench</p>
            <div>
              <h2 className="text-sm font-semibold text-slate-100">Settings Flow</h2>
              <p className="text-xs text-slate-400">
                Tune the identity, runtime, and autonomy rules for {displayName}.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onMobileClose}
            aria-label="Close sidebar"
            className="icon-button h-9 w-9 lg:hidden"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="space-y-2 flex-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => handleTabClick(tab.id)}
              className={cn(
                "group w-full rounded-2xl border px-3 py-3 text-left transition",
                activeTab === tab.id
                  ? "border-amber-500/30 bg-amber-500/10 text-amber-100"
                  : "border-transparent bg-slate-950/25 text-slate-300 hover:border-slate-700/80 hover:bg-slate-950/70",
              )}
            >
              <div className="flex items-start gap-3">
                <span
                  className={cn(
                    "mt-0.5 flex h-9 w-9 items-center justify-center rounded-2xl border transition",
                    activeTab === tab.id
                      ? "border-amber-400/25 bg-amber-500/10 text-amber-200"
                      : "border-slate-800 bg-slate-900/90 text-slate-400 group-hover:border-slate-700 group-hover:text-slate-200",
                  )}
                >
                  <tab.icon className="h-4 w-4 flex-shrink-0" />
                </span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-medium">{tab.label}</span>
                    <ChevronRight
                      className={cn(
                        "h-4 w-4 transition",
                        activeTab === tab.id ? "text-amber-300" : "text-slate-600 group-hover:text-slate-400",
                      )}
                    />
                  </div>
                  <p className="mt-1 text-xs leading-5 text-slate-500 group-hover:text-slate-400">
                    {tab.description}
                  </p>
                </div>
              </div>
            </button>
          ))}
        </div>

        {(personaName || version != null) && (
          <div className="mt-5 rounded-2xl border border-slate-800/80 bg-slate-950/60 p-4">
            <p className="section-kicker">Snapshot</p>
            {personaName && (
              <p className="mt-3 text-sm font-medium text-slate-300 truncate">
                {personaName}
              </p>
            )}
            {version != null && (
              <p className="text-xs font-mono text-slate-400 mt-1">
                v{version}
              </p>
            )}
            {updatedAt && (
              <p className="text-[11px] text-slate-400 mt-2">
                Updated {new Date(updatedAt).toLocaleDateString()}
              </p>
            )}
          </div>
        )}
      </nav>
    </>
  );
}
