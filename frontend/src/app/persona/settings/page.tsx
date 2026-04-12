"use client";

import { useCallback, useState } from "react";
import { Loader2, Menu } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";

import type { PersonaTabId } from "./types";
import { usePersonaSettings } from "./hooks/usePersonaSettings";
import { PersonaSettingsHeader } from "./components/PersonaSettingsHeader";
import {
  PersonaSettingsSidebar,
  PERSONA_SETTINGS_TABS,
} from "./components/PersonaSettingsSidebar";
import { IdentityTab } from "./components/IdentityTab";
import { VoiceHeartbeatTab } from "./components/VoiceHeartbeatTab";
import { SessionLimitsTab } from "./components/SessionLimitsTab";

// Reuse agent tab components directly
import { ModelsTab } from "@/app/agents/[slug]/components/ModelsTab";
import { ParametersTab } from "@/app/agents/[slug]/components/ParametersTab";
import { PromptsTab } from "@/app/agents/[slug]/components/PromptsTab";
import { MemoryTab } from "@/app/agents/[slug]/components/MemoryTab";
import type { PreviewScenario, PreviewTaskType } from "@/app/agents/[slug]/types";
import { useAgentPreview } from "@/app/agents/[slug]/hooks/useAgentPreview";
import { DEFAULT_PREVIEW_SCENARIO } from "@/types/agent-preview";

function isPersonaTab(value: string | null): value is PersonaTabId {
  return PERSONA_SETTINGS_TABS.some((tab) => tab.id === value);
}

export default function PersonaSettingsPage() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const [showInlinePreview, setShowInlinePreview] = useState(false);
  const [previewMode, setPreviewMode] = useState<PreviewTaskType>("heartbeat");
  const [previewScenario, setPreviewScenario] = useState<PreviewScenario>(() => ({
    ...DEFAULT_PREVIEW_SCENARIO,
  }));
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const {
    persona,
    personaLoading,
    personaError,
    updatePersonaField,
    personaAutosave,
    agent,
    agentLoading,
    agentError,
    agentFormData,
    hasAgentChanges,
    updateAgentField,
    saveAgent,
    isSaving,
    saveSuccess,
    saveError,
    availableModels,
    refreshPersona,
  } = usePersonaSettings();
  const {
    data: preview,
    isFetching: previewFetching,
    refetch: refetchPreview,
    error: previewQueryError,
  } = useAgentPreview({
    slug: "persona",
    previewMode,
    scenario: previewScenario,
    enabled: showInlinePreview,
  });
  const updatePreviewScenario = useCallback((updates: Partial<PreviewScenario>) => {
    setPreviewScenario((prev) => ({ ...prev, ...updates }));
  }, []);
  const setActiveTab = useCallback((tab: PersonaTabId) => {
    const nextParams = new URLSearchParams(searchParams.toString());
    if (tab === "identity") {
      nextParams.delete("tab");
    } else {
      nextParams.set("tab", tab);
    }
    const query = nextParams.toString();
    router.replace(query ? `${pathname}?${query}` : pathname, { scroll: false });
  }, [pathname, router, searchParams]);
  const previewError =
    previewQueryError instanceof Error
      ? previewQueryError.message
      : previewQueryError
        ? "Failed to load preview"
        : null;
  const tabParam = searchParams.get("tab");
  const activeTab: PersonaTabId = isPersonaTab(tabParam) ? tabParam : "identity";
  const activeTabMeta =
    PERSONA_SETTINGS_TABS.find((tab) => tab.id === activeTab) ?? PERSONA_SETTINGS_TABS[0];

  if (personaLoading || agentLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (personaError || agentError) {
    return (
      <div className="flex min-h-screen items-center justify-center px-6">
        <div className="max-w-md text-center space-y-2">
          <p className="text-sm font-medium text-rose-400">
            Failed to load persona settings
          </p>
          <p className="text-sm text-slate-400">
            {personaError || agentError}
          </p>
        </div>
      </div>
    );
  }

  if (!persona || !agent) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-slate-500">Persona not configured</p>
      </div>
    );
  }

  return (
    <div className="page-shell flex flex-col">
      <div className="page-backdrop" />
      <PersonaSettingsHeader
        personaName={persona.name}
        hasChanges={hasAgentChanges}
        isSaving={isSaving}
        saveSuccess={saveSuccess}
        saveError={saveError}
        onSave={saveAgent}
        backHref={sessionId ? `/persona?session_id=${sessionId}` : "/persona"}
      />

      <div className="page-container flex-1">
        <div className="page-frame">
          <div className="flex flex-col gap-6 xl:flex-row">
        <PersonaSettingsSidebar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          personaName={persona.name}
          version={agent.version}
          updatedAt={agent.updated_at}
          mobileOpen={sidebarOpen}
          onMobileClose={() => setSidebarOpen(false)}
        />

            <main className="min-w-0 flex-1 overflow-y-auto">
          {/* Mobile tab bar */}
          <div className="panel-surface mb-4 flex items-center gap-2 px-4 py-3 lg:hidden">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="icon-button h-10 w-10"
              aria-label="Open settings menu"
            >
              <Menu className="h-5 w-5" />
            </button>
            {(() => {
              const currentTab = PERSONA_SETTINGS_TABS.find((t) => t.id === activeTab);
              if (!currentTab) return null;
              return (
                <div className="flex items-center gap-2 text-sm font-medium text-slate-300">
                  <currentTab.icon className="h-4 w-4" />
                  {currentTab.label}
                </div>
              );
            })()}
          </div>

              <section className="panel-surface animate-fade-up">
                <div className="border-b border-slate-800/80 px-5 py-5 lg:px-6">
                  <div className="section-header gap-4">
                    <div>
                      <p className="section-kicker">Runtime Profile</p>
                      <h2 className="section-heading mt-2">{activeTabMeta.label}</h2>
                      <p className="section-copy mt-2 max-w-3xl">
                        {activeTabMeta.description}
                      </p>
                    </div>
                    <div className="page-meta">
                      <span className="page-pill">Persona runtime</span>
                      <span className="page-pill">Identity autosave</span>
                    </div>
                  </div>
                </div>
                <div className="px-5 py-5 lg:px-6 lg:py-6">
                  <div className="max-w-5xl">
              {activeTab === "identity" && (
                <IdentityTab persona={persona} onUpdate={updatePersonaField} onPersonaRefresh={refreshPersona} />
              )}
              {activeTab === "models" && (
                <div className="space-y-8">
                  <ModelsTab
                    formData={agentFormData}
                    availableModels={availableModels}
                    updateField={updateAgentField}
                  />
                  <ParametersTab
                    formData={agentFormData}
                    availableModels={availableModels}
                    updateField={updateAgentField}
                  />
                </div>
              )}
              {activeTab === "prompts" && (
                <PromptsTab
                  agentSlug="persona"
                  preview={preview}
                  previewFetching={previewFetching}
                  previewError={previewError}
                  showInlinePreview={showInlinePreview}
                  setShowInlinePreview={setShowInlinePreview}
                  previewMode={previewMode}
                  setPreviewMode={setPreviewMode}
                  previewScenario={previewScenario}
                  onPreviewScenarioChange={updatePreviewScenario}
                  refetchPreview={refetchPreview}
                />
              )}
              {activeTab === "voice" && (
                <VoiceHeartbeatTab
                  persona={persona}
                  onUpdate={updatePersonaField}
                  autosave={personaAutosave}
                />
              )}
              {activeTab === "session" && (
                <SessionLimitsTab persona={persona} onUpdate={updatePersonaField} />
              )}
              {activeTab === "memory" && (
                <MemoryTab
                  formData={agentFormData}
                  updateField={updateAgentField}
                />
              )}
                  </div>
                </div>
              </section>
            </main>
          </div>
        </div>
      </div>
    </div>
  );
}
