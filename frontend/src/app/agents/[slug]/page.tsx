"use client";

import { useState, useEffect, useCallback } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Bot,
  Save,
  ArrowLeft,
  Settings2,
  Cpu,
  FileText,
  Sliders,
  AlertCircle,
  CheckCircle2,
  Loader2,
  Play,
  Eye,
  X,
  Plus,
  Trash2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

// ─────────────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────────────

interface Agent {
  id: number;
  slug: string;
  name: string;
  description: string | null;
  system_prompt: string;
  primary_model_id: string;
  fallback_models: string[];
  escalation_model_id: string | null;
  strategies: Record<string, unknown>;
  temperature: number;
  is_active: boolean;
  version: number;
  created_at: string;
  updated_at: string;
}

interface AgentPreview {
  slug: string;
  name: string;
  combined_prompt: string;
  mandate_count: number;
  mandate_uuids: string[];
}

type TabId = "general" | "models" | "prompt" | "parameters";

// ─────────────────────────────────────────────────────────────────────────────
// API
// ─────────────────────────────────────────────────────────────────────────────

async function fetchAgent(slug: string): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`);
  if (!res.ok) throw new Error("Failed to fetch agent");
  return res.json();
}

async function updateAgent(
  slug: string,
  data: Partial<Agent>
): Promise<Agent> {
  const res = await fetchApi(`/api/agents/${slug}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update agent");
  return res.json();
}

async function fetchPreview(slug: string): Promise<AgentPreview> {
  const res = await fetchApi(`/api/agents/${slug}/preview`);
  if (!res.ok) throw new Error("Failed to fetch preview");
  return res.json();
}

// ─────────────────────────────────────────────────────────────────────────────
// AVAILABLE MODELS - fetched from API
// ─────────────────────────────────────────────────────────────────────────────

interface ModelInfo {
  id: string;
  name: string;
  provider: string;
}

async function fetchModels(): Promise<ModelInfo[]> {
  try {
    const res = await fetchApi("/api/models");
    if (!res.ok) throw new Error("Failed to fetch models");
    const data = await res.json();
    return data.models || [];
  } catch {
    return [
      { id: "claude-sonnet-4-5", name: "Claude Sonnet 4.5", provider: "claude" },
      { id: "claude-haiku-4-5", name: "Claude Haiku 4.5", provider: "claude" },
      { id: "gemini-3-flash-preview", name: "Gemini 3 Flash", provider: "gemini" },
    ];
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// COMPONENTS
// ─────────────────────────────────────────────────────────────────────────────

const TABS: { id: TabId; label: string; icon: React.ElementType }[] = [
  { id: "general", label: "General", icon: Settings2 },
  { id: "models", label: "Models", icon: Cpu },
  { id: "prompt", label: "Prompt", icon: FileText },
  { id: "parameters", label: "Parameters", icon: Sliders },
];

function ModelSelect({
  value,
  onChange,
  label,
  models,
  allowNull = false,
}: {
  value: string | null;
  onChange: (value: string | null) => void;
  label: string;
  models: ModelInfo[];
  allowNull?: boolean;
}) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        {label}
      </label>
      <select
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value || null)}
        className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
      >
        {allowNull && <option value="">None</option>}
        {models.map((model) => (
          <option key={model.id} value={model.id}>
            {model.name}
          </option>
        ))}
      </select>
    </div>
  );
}

function FallbackModelsList({
  selectedModels,
  availableModels,
  onChange,
}: {
  selectedModels: string[];
  availableModels: ModelInfo[];
  onChange: (models: string[]) => void;
}) {
  const addModel = () => {
    const available = availableModels.filter((m) => !selectedModels.includes(m.id));
    if (available.length > 0) {
      onChange([...selectedModels, available[0].id]);
    }
  };

  const removeModel = (index: number) => {
    onChange(selectedModels.filter((_, i) => i !== index));
  };

  const updateModel = (index: number, value: string) => {
    const updated = [...selectedModels];
    updated[index] = value;
    onChange(updated);
  };

  return (
    <div className="space-y-2">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        Fallback Models (in order)
      </label>
      {selectedModels.length === 0 ? (
        <p className="text-xs text-slate-400 italic">No fallback models configured</p>
      ) : (
        <div className="space-y-2">
          {selectedModels.map((model, index) => (
            <div key={index} className="flex items-center gap-2">
              <select
                value={model}
                onChange={(e) => updateModel(index, e.target.value)}
                className="flex-1 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
              >
                {availableModels.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                  </option>
                ))}
              </select>
              <button
                onClick={() => removeModel(index)}
                className="p-2 rounded-lg hover:bg-red-50 dark:hover:bg-red-950/20 text-red-500"
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          ))}
        </div>
      )}
      <button
        onClick={addModel}
        disabled={selectedModels.length >= availableModels.length - 1}
        className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium text-blue-600 hover:bg-blue-50 dark:hover:bg-blue-950/20 rounded-lg transition-colors disabled:opacity-50"
      >
        <Plus className="h-3.5 w-3.5" />
        Add Fallback
      </button>
    </div>
  );
}

function PromptEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  // Highlight variables like {{variable}} or {variable}
  const highlightedText = value.replace(
    /\{\{?[\w_]+\}?\}/g,
    (match) => `<span class="text-blue-500 font-semibold">${match}</span>`
  );

  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
        System Prompt
      </label>
      <div className="relative">
        <textarea
          value={value}
          onChange={(e) => onChange(e.target.value)}
          rows={20}
          className="w-full px-4 py-3 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-y"
          placeholder="Enter system prompt..."
        />
        <div className="absolute bottom-2 right-2 text-[10px] text-slate-400 font-mono">
          {value.length} chars
        </div>
      </div>
      <p className="text-[10px] text-slate-400">
        Variables like {"{{variable}}"} will be highlighted. Mandates are injected based on tags.
      </p>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// MAIN PAGE
// ─────────────────────────────────────────────────────────────────────────────

export default function AgentEditorPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const slug = params.slug as string;

  const [activeTab, setActiveTab] = useState<TabId>("general");
  const [formData, setFormData] = useState<Partial<Agent>>({});
  const [hasChanges, setHasChanges] = useState(false);
  const [showPreview, setShowPreview] = useState(false);

  const { data: agent, isLoading, error } = useQuery({
    queryKey: ["agent", slug],
    queryFn: () => fetchAgent(slug),
    enabled: !!slug,
  });

  const { data: availableModels = [] } = useQuery({
    queryKey: ["models"],
    queryFn: fetchModels,
  });

  const { data: preview, refetch: refetchPreview } = useQuery({
    queryKey: ["agent-preview", slug],
    queryFn: () => fetchPreview(slug),
    enabled: showPreview && !!slug,
  });

  const mutation = useMutation({
    mutationFn: (data: Partial<Agent>) => updateAgent(slug, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["agent", slug] });
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      setHasChanges(false);
    },
  });

  // Unsaved changes warning
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

  // Initialize form data when agent loads
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
      {/* HEADER */}
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-6 lg:px-8">
          <div className="flex items-center justify-between h-14">
            <div className="flex items-center gap-4">
              <button
                onClick={() => router.push("/agents")}
                className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
              >
                <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
              </button>
              <div className="flex items-center gap-2">
                <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100 tracking-tight">
                  {agent.name}
                </h1>
                <span className="text-xs font-mono text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded">
                  {agent.slug}
                </span>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {hasChanges && (
                <span className="text-xs text-amber-600 dark:text-amber-400">
                  Unsaved changes
                </span>
              )}
              <button
                onClick={() => {
                  setShowPreview(true);
                  refetchPreview();
                }}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
              >
                <Eye className="h-3.5 w-3.5" />
                Preview
              </button>
              <a
                href={`/agents/${slug}/playground`}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
              >
                <Play className="h-3.5 w-3.5" />
                Playground
              </a>
              <button
                onClick={handleSave}
                disabled={!hasChanges || mutation.isPending}
                className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
              >
                {mutation.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Save className="h-3.5 w-3.5" />
                )}
                Save
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* Success/Error Toast */}
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

      {/* MAIN CONTENT */}
      <div className="flex">
        {/* VERTICAL TABS */}
        <nav className="w-48 min-h-[calc(100vh-3.5rem)] border-r border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
          <div className="space-y-1">
            {TABS.map((tab) => (
              <button
                key={tab.id}
                onClick={() => setActiveTab(tab.id)}
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

          {/* Version Info */}
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

        {/* TAB CONTENT */}
        <main className="flex-1 p-6 lg:p-8">
          <div className="max-w-2xl">
            {/* GENERAL TAB */}
            {activeTab === "general" && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
                    General Settings
                  </h2>
                </div>

                <div className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                      Name
                    </label>
                    <input
                      type="text"
                      value={formData.name ?? ""}
                      onChange={(e) => updateField("name", e.target.value)}
                      className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                      Description
                    </label>
                    <textarea
                      value={formData.description ?? ""}
                      onChange={(e) => updateField("description", e.target.value)}
                      rows={3}
                      className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-y"
                    />
                  </div>

                  <div className="space-y-1.5">
                    <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                      Status
                    </label>
                    <div className="flex items-center gap-3">
                      <button
                        onClick={() => updateField("is_active", true)}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                          formData.is_active
                            ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800 text-emerald-600"
                            : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50"
                        )}
                      >
                        <CheckCircle2 className="h-4 w-4" />
                        Active
                      </button>
                      <button
                        onClick={() => updateField("is_active", false)}
                        className={cn(
                          "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                          !formData.is_active
                            ? "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-700"
                            : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50"
                        )}
                      >
                        Inactive
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* MODELS TAB */}
            {activeTab === "models" && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
                    Model Configuration
                  </h2>
                </div>

                <div className="space-y-6">
                  <ModelSelect
                    label="Primary Model"
                    value={formData.primary_model_id ?? null}
                    onChange={(v) => updateField("primary_model_id", v ?? "")}
                    models={availableModels}
                  />

                  <FallbackModelsList
                    selectedModels={formData.fallback_models ?? []}
                    availableModels={availableModels}
                    onChange={(models) => updateField("fallback_models", models)}
                  />

                  <ModelSelect
                    label="Escalation Model (for complex tasks)"
                    value={formData.escalation_model_id ?? null}
                    onChange={(v) => updateField("escalation_model_id", v)}
                    models={availableModels}
                    allowNull
                  />
                </div>
              </div>
            )}

            {/* PROMPT TAB */}
            {activeTab === "prompt" && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
                    System Prompt
                  </h2>
                </div>

                <PromptEditor
                  value={formData.system_prompt ?? ""}
                  onChange={(v) => updateField("system_prompt", v)}
                />
              </div>
            )}

            {/* PARAMETERS TAB */}
            {activeTab === "parameters" && (
              <div className="space-y-6">
                <div>
                  <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
                    Generation Parameters
                  </h2>
                </div>

                <div className="space-y-6">
                  {/* Temperature Slider */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                        Temperature
                      </label>
                      <span className="text-sm font-mono text-slate-700 dark:text-slate-300">
                        {(formData.temperature ?? 0.7).toFixed(2)}
                      </span>
                    </div>
                    <input
                      type="range"
                      min="0"
                      max="2"
                      step="0.1"
                      value={formData.temperature ?? 0.7}
                      onChange={(e) =>
                        updateField("temperature", parseFloat(e.target.value))
                      }
                      className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
                    />
                    <div className="flex justify-between text-[10px] text-slate-400">
                      <span>Precise (0)</span>
                      <span>Balanced (1)</span>
                      <span>Creative (2)</span>
                    </div>
                  </div>

                </div>
              </div>
            )}

          </div>
        </main>
      </div>

      {/* PREVIEW MODAL */}
      {showPreview && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
          <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] overflow-hidden">
            <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
              <div>
                <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  Combined Prompt Preview
                </h3>
                {preview && (
                  <p className="text-xs text-slate-500">
                    {preview.mandate_count} mandates injected
                  </p>
                )}
              </div>
              <button
                onClick={() => setShowPreview(false)}
                className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
              >
                <X className="h-5 w-5" />
              </button>
            </div>
            <div className="p-6 overflow-y-auto max-h-[60vh]">
              {preview ? (
                <pre className="whitespace-pre-wrap text-sm font-mono text-slate-700 dark:text-slate-300 bg-slate-50 dark:bg-slate-800 p-4 rounded-lg">
                  {preview.combined_prompt}
                </pre>
              ) : (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
