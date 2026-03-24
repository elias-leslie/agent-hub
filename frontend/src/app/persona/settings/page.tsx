"use client";

import { useCallback, useState } from "react";
import { Loader2, Menu } from "lucide-react";
import { useSearchParams } from "next/navigation";

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
import { PermissionsTab } from "@/app/agents/[slug]/components/PermissionsTab";
import { MemoryTab } from "@/app/agents/[slug]/components/MemoryTab";
import type { PreviewScenario, PreviewTaskType } from "@/app/agents/[slug]/types";
import { useAgentPreview } from "@/app/agents/[slug]/hooks/useAgentPreview";
import { DEFAULT_PREVIEW_SCENARIO } from "@/types/agent-preview";

export default function PersonaSettingsPage() {
  const searchParams = useSearchParams();
  const sessionId = searchParams.get("session_id");
  const [activeTab, setActiveTab] = useState<PersonaTabId>("identity");
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
  const previewError =
    previewQueryError instanceof Error
      ? previewQueryError.message
      : previewQueryError
        ? "Failed to load preview"
        : null;

  if (personaLoading || agentLoading) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (personaError || agentError) {
    return (
      <div className="min-h-screen bg-slate-950 flex items-center justify-center px-6">
        <div className="max-w-md text-center space-y-2">
          <p className="text-sm font-medium text-rose-500 dark:text-rose-400">
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
      <div className="min-h-screen bg-slate-950 flex items-center justify-center">
        <p className="text-sm text-slate-500">Persona not configured</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 flex flex-col">
      <PersonaSettingsHeader
        personaName={persona.name}
        hasChanges={hasAgentChanges}
        isSaving={isSaving}
        saveSuccess={saveSuccess}
        saveError={saveError}
        onSave={saveAgent}
        backHref={sessionId ? `/persona?session_id=${sessionId}` : "/persona"}
      />

      <div className="flex flex-1 h-[calc(100vh-3.5rem)] overflow-hidden">
        <PersonaSettingsSidebar
          activeTab={activeTab}
          onTabChange={setActiveTab}
          personaName={persona.name}
          version={agent.version}
          updatedAt={agent.updated_at}
          mobileOpen={sidebarOpen}
          onMobileClose={() => setSidebarOpen(false)}
        />

        <main className="flex-1 overflow-y-auto">
          {/* Mobile tab bar */}
          <div className="flex items-center gap-2 px-4 py-3 border-b border-slate-800 bg-slate-900 lg:hidden">
            <button
              type="button"
              onClick={() => setSidebarOpen(true)}
              className="p-1.5 rounded-md text-slate-400 hover:bg-slate-800 transition-colors"
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

          <div className="p-6 lg:p-8">
            <div className="max-w-2xl">
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
              {activeTab === "permissions" && (
                <PermissionsTab
                  formData={agentFormData}
                  updateField={updateAgentField}
                />
              )}
              {activeTab === "memory" && (
                <MemoryTab
                  formData={agentFormData}
                  updateField={updateAgentField}
                />
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
}
