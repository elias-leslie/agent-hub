import { useState, useEffect, useCallback, useRef } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchApi, buildApiUrl } from "@/lib/api-config";
import { fetchAgent, updateAgent, fetchPreview, fetchModels } from "@/lib/api";
import { useToastActions } from "@/components/error/toast";
import type { Persona, PersonaUpdate } from "@/types/persona";
import type { Agent, AgentPreview, ModelInfo } from "@/app/agents/[slug]/types";

const PERSONA_SLUG = "persona";

export function usePersonaSettings() {
  const queryClient = useQueryClient();
  const toast = useToastActions();

  // --- Persona (auto-save) ---
  const [persona, setPersona] = useState<Persona | null>(null);
  const [personaLoading, setPersonaLoading] = useState(true);
  const saveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const res = await fetchApi(buildApiUrl("/api/persona"));
        if (!res.ok) throw new Error(`${res.status}`);
        const data = await res.json();
        if (!cancelled) setPersona(data);
      } catch {
        // persona not configured
      } finally {
        if (!cancelled) setPersonaLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const updatePersonaField = useCallback((fields: PersonaUpdate) => {
    setPersona((prev) => (prev ? { ...prev, ...fields } : prev));
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(async () => {
      try {
        const res = await fetchApi(buildApiUrl("/api/persona"), {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(fields),
        });
        if (res.ok) {
          const updated = await res.json();
          setPersona(updated);
        }
      } catch (err) {
        console.error("Failed to save persona:", err);
      }
    }, 500);
  }, []);

  // --- Agent (explicit save) ---
  const {
    data: agent,
    isLoading: agentLoading,
  } = useQuery({
    queryKey: ["agent", PERSONA_SLUG],
    queryFn: () => fetchAgent(PERSONA_SLUG),
  });

  const { data: availableModels = [] } = useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
  });

  const { data: preview, refetch: refetchPreview, isFetching: previewFetching } = useQuery({
    queryKey: ["agent-preview", PERSONA_SLUG],
    queryFn: () => fetchPreview(PERSONA_SLUG),
    enabled: false,
  });

  const [agentFormData, setAgentFormData] = useState<Partial<Agent>>({});
  const [hasAgentChanges, setHasAgentChanges] = useState(false);

  useEffect(() => {
    if (agent) {
      setAgentFormData({
        name: agent.name,
        description: agent.description,
        system_prompt: agent.system_prompt,
        primary_model_id: agent.primary_model_id,
        fallback_models: agent.fallback_models,
        escalation_model_id: agent.escalation_model_id,
        temperature: agent.temperature,
        is_active: agent.is_active,
        is_coding_agent: agent.is_coding_agent,
        tool_permissions: agent.tool_permissions,
        memory_config: agent.memory_config,
      });
      setHasAgentChanges(false);
    }
  }, [agent]);

  const updateAgentField = useCallback(<K extends keyof Agent>(field: K, value: Agent[K]) => {
    setAgentFormData((prev) => ({ ...prev, [field]: value }));
    setHasAgentChanges(true);
  }, []);

  const saveMutation = useMutation({
    mutationFn: (data: Partial<Agent>) => updateAgent(PERSONA_SLUG, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent", PERSONA_SLUG] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      setHasAgentChanges(false);
    },
  });

  const saveAgent = useCallback(() => {
    // Strip empty strings for fields with backend min_length constraints
    // so the API treats them as "don't update" rather than failing validation
    const payload = { ...agentFormData };
    if (!payload.system_prompt) delete payload.system_prompt;
    if (!payload.name) delete payload.name;
    if (!payload.primary_model_id) delete payload.primary_model_id;
    saveMutation.mutate(payload);
  }, [saveMutation, agentFormData]);

  return {
    // Persona
    persona,
    personaLoading,
    updatePersonaField,
    refreshPersona: setPersona,

    // Agent
    agent,
    agentLoading,
    agentFormData,
    hasAgentChanges,
    updateAgentField,
    saveAgent,
    isSaving: saveMutation.isPending,
    saveSuccess: saveMutation.isSuccess,
    saveError: saveMutation.isError,

    // Models
    availableModels,

    // Preview
    preview,
    previewFetching,
    refetchPreview,
  };
}
