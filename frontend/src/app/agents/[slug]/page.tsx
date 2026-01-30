"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";
import { Agent, TabId } from "./types";
import { fetchAgent, updateAgent, fetchPreview, fetchModels } from "./api";
import { AgentEditorHeader } from "./components/AgentEditorHeader";
import { Sidebar } from "./components/Sidebar";
import { GeneralTab } from "./components/GeneralTab";
import { ModelsTab } from "./components/ModelsTab";
import { PromptTab } from "./components/PromptTab";
import { ParametersTab } from "./components/ParametersTab";
import { PreviewModal } from "./components/PreviewModal";

export default function AgentEditorPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const slug = params.slug as string;

  const [activeTab, setActiveTab] = useState<TabId>("general");
  const [formData, setFormData] = useState<Partial<Agent>>({});
  const [hasChanges, setHasChanges] = useState(false);
  const [showPreview, setShowPreview] = useState(false);
  const [showInlinePreview, setShowInlinePreview] = useState(false);

  const { data: agent, isLoading, error } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  });

  const { data: availableModels = [] } = useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
  });

  const { data: preview, refetch: refetchPreview, isFetching: previewFetching } = useQuery({
    queryKey: ["agent-preview", slug],
    queryFn: () => fetchPreview(slug),
    enabled: (showPreview || showInlinePreview) && !!slug,
  });

  const mutation = useMutation({
    mutationFn: (data: Partial<Agent>) => updateAgent(slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent", slug] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      setHasChanges(false);
    },
  });

  useEffect(() => {
    const handleBeforeUnload = (e: BeforeUnloadEvent) => {
      if (hasChanges) {
        e.preventDefault();
        e.returnValue = "You have unsaved changes. Are you sure you want to leave?";
        return e.returnValue;
      }
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasChanges]);

  useEffect(() => {
    if (agent) {
      setFormData({
        name: agent.name,
        description: agent.description,
        system_prompt: agent.system_prompt,
        primary_model_id: agent.primary_model_id,
        fallback_models: agent.fallback_models,
        escalation_model_id: agent.escalation_model_id,
        temperature: agent.temperature,
        is_active: agent.is_active,
      });
    }
  }, [agent]);

  const updateField = useCallback(<K extends keyof Agent>(field: K, value: Agent[K]) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    setHasChanges(true);
  }, []);

  const handleSave = () => {
    mutation.mutate(formData);
  };

  const handlePreview = () => {
    setShowPreview(true);
    refetchPreview();
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !agent) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Agent not found
          </p>
          <button
            onClick={() => router.push("/agents")}
            className="mt-4 px-4 py-2 text-sm font-medium text-blue-600 hover:underline"
          >
            Back to Agents
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <AgentEditorHeader
        agent={agent}
        hasChanges={hasChanges}
        isSaving={mutation.isPending}
        onSave={handleSave}
        onPreview={handlePreview}
      />

      {mutation.isSuccess && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-600 dark:text-emerald-400 text-sm shadow-lg">
          <CheckCircle2 className="h-4 w-4" />
          Agent saved successfully
        </div>
      )}
      {mutation.isError && (
        <div className="fixed top-20 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to save agent
        </div>
      )}

      <div className="flex">
        <Sidebar
          activeTab={activeTab}
          agent={agent}
          onTabChange={setActiveTab}
        />

        <main className="flex-1 p-6 lg:p-8">
          <div className="max-w-2xl">
            {activeTab === "general" && (
              <GeneralTab formData={formData} updateField={updateField} />
            )}
            {activeTab === "models" && (
              <ModelsTab
                formData={formData}
                availableModels={availableModels}
                updateField={updateField}
              />
            )}
            {activeTab === "prompt" && (
              <PromptTab
                formData={formData}
                preview={preview}
                previewFetching={previewFetching}
                showInlinePreview={showInlinePreview}
                setShowInlinePreview={setShowInlinePreview}
                updateField={updateField}
                refetchPreview={refetchPreview}
              />
            )}
            {activeTab === "parameters" && (
              <ParametersTab formData={formData} updateField={updateField} />
            )}
          </div>
        </main>
      </div>

      {showPreview && (
        <PreviewModal
          preview={preview}
          onClose={() => setShowPreview(false)}
        />
      )}
    </div>
  );
}
