"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Save,
  Trash2,
  Loader2,
  AlertCircle,
  CheckCircle2,
  Globe,
} from "lucide-react";
import {
  deletePrompt,
  fetchPrompt,
  fetchPromptRevisions,
  restorePromptRevision,
  updatePrompt,
} from "@/lib/api/prompts";
import { PromptRevisionHistory } from "@/app/prompts/[slug]/components/PromptRevisionHistory";
import { cn } from "@/lib/utils";

export default function PromptEditPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const slug = params.slug as string;

  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [description, setDescription] = useState("");
  const [isGlobal, setIsGlobal] = useState(false);
  const [enabled, setEnabled] = useState(true);
  const [excludeAgents, setExcludeAgents] = useState<string[]>([]);
  const [excludeInput, setExcludeInput] = useState("");
  const [changeReason, setChangeReason] = useState("");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const {
    data: prompt,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["prompt", slug],
    queryFn: () => fetchPrompt(slug),
    enabled: !!slug,
  });

  const {
    data: revisions = [],
    isLoading: revisionsLoading,
  } = useQuery({
    queryKey: ["prompt-revisions", slug],
    queryFn: () => fetchPromptRevisions(slug),
    enabled: !!slug,
  });

  useEffect(() => {
    if (prompt) {
      setName(prompt.name);
      setContent(prompt.content);
      setDescription(prompt.description ?? "");
      setIsGlobal(prompt.is_global);
      setEnabled(prompt.enabled);
      setExcludeAgents(prompt.exclude_agents ?? []);
    }
  }, [prompt]);

  const saveMutation = useMutation({
    mutationFn: () =>
      updatePrompt(slug, {
        name,
        content,
        description: description || undefined,
        is_global: isGlobal,
        enabled,
        exclude_agents: excludeAgents,
        change_reason: changeReason || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompt", slug] });
      queryClient.invalidateQueries({ queryKey: ["prompt-revisions", slug] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setChangeReason("");
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (revisionId: string) =>
      restorePromptRevision(
        slug,
        revisionId,
        changeReason || `Restore ${slug} revision`,
      ),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompt", slug] });
      queryClient.invalidateQueries({ queryKey: ["prompt-revisions", slug] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setChangeReason("");
    },
  });

  const deleteMutation = useMutation({
    mutationFn: () => deletePrompt(slug),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      router.push("/prompts");
    },
  });

  const handleDelete = () => {
    if (confirmDelete) {
      deleteMutation.mutate();
    } else {
      setConfirmDelete(true);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (error || !prompt) {
    return (
      <div className="min-h-screen bg-slate-50 dark:bg-slate-950 flex items-center justify-center">
        <div className="text-center">
          <AlertCircle className="h-10 w-10 text-red-500 mx-auto mb-3" />
          <p className="text-sm text-slate-600 dark:text-slate-400">
            Prompt not found
          </p>
          <button
            onClick={() => router.push("/prompts")}
            className="mt-4 px-4 py-2 text-sm font-medium text-blue-600 hover:underline"
          >
            Back to Prompts
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Toast notifications */}
      {saveMutation.isSuccess && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200 dark:border-emerald-800 text-emerald-600 dark:text-emerald-400 text-sm shadow-lg">
          <CheckCircle2 className="h-4 w-4" />
          Prompt saved successfully
        </div>
      )}
      {saveMutation.isError && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to save prompt
        </div>
      )}
      {deleteMutation.isError && (
        <div className="fixed top-6 right-6 z-50 flex items-center gap-2 px-4 py-2 rounded-lg bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 text-sm shadow-lg">
          <AlertCircle className="h-4 w-4" />
          Failed to delete prompt
        </div>
      )}

      {/* Header */}
      <div className="border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 px-6 py-4">
        <div className="max-w-4xl mx-auto flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => router.push("/prompts")}
              className="p-1.5 rounded-lg text-slate-400 hover:text-slate-600 dark:hover:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5" />
            </button>
            <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              {prompt.name}
            </h1>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={handleDelete}
              disabled={deleteMutation.isPending || prompt.deletion_locked}
              className="px-4 py-2 text-sm font-medium rounded-lg border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <span className="flex items-center gap-2">
                  <Trash2 className="h-4 w-4" />
                  {prompt.deletion_locked ? "Locked" : confirmDelete ? "Confirm Delete" : "Delete"}
                </span>
              )}
            </button>
            <button
              onClick={() => saveMutation.mutate()}
              disabled={saveMutation.isPending}
              className="px-4 py-2 text-sm font-medium rounded-lg bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {saveMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" />
              ) : (
                <span className="flex items-center gap-2">
                  <Save className="h-4 w-4" />
                  Save
                </span>
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Form */}
      <div className="max-w-5xl mx-auto px-6 py-8">
        <div className="space-y-6">
          {/* Slug (readonly) */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Slug
            </label>
            <div className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 text-sm font-mono text-slate-500 dark:text-slate-400">
              {prompt.slug}
            </div>
            {prompt.owner_agent_slug && (
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                Owned by agent: {prompt.owner_agent_slug}
              </p>
            )}
            {prompt.deletion_locked && (
              <p className="text-[11px] text-amber-600 dark:text-amber-300">
                This prompt is locked and cannot be deleted.
              </p>
            )}
          </div>

          {/* Name */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Name
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
          </div>

          {/* Content */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Content
            </label>
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              style={{ minHeight: "300px" }}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-y"
            />
          </div>

          {/* Description */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Description
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={3}
              className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40 resize-y"
            />
          </div>

          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Change Reason
            </label>
            <input
              type="text"
              value={changeReason}
              onChange={(e) => setChangeReason(e.target.value)}
              placeholder="Why are you changing this prompt?"
              className="w-full px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            />
            <p className="text-[11px] text-slate-500 dark:text-slate-400">
              Saved with every update and restore so Arena and benchmark runs can
              attribute regressions to prompt changes.
            </p>
          </div>

          {/* Is Global toggle */}
          <div className="space-y-1.5">
            <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Scope & Status
            </label>
            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={() => setIsGlobal(true)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  isGlobal
                    ? "bg-blue-50 dark:bg-blue-950/40 border-blue-200 dark:border-blue-800 text-blue-600"
                    : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50",
                )}
              >
                <Globe className="h-4 w-4" />
                Global
              </button>
              <button
                onClick={() => setIsGlobal(false)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  !isGlobal
                    ? "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-700"
                    : "border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400 hover:bg-slate-50",
                )}
              >
                Non-Global
              </button>
              <button
                onClick={() => setEnabled(!enabled)}
                className={cn(
                  "flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium border transition-colors",
                  enabled
                    ? "bg-emerald-50 dark:bg-emerald-950/40 border-emerald-200 dark:border-emerald-800 text-emerald-600"
                    : "bg-slate-100 dark:bg-slate-800 border-slate-300 dark:border-slate-600 text-slate-600 dark:text-slate-400",
                )}
              >
                {enabled ? "Enabled" : "Disabled"}
              </button>
            </div>
          </div>

          {/* Excluded Agents (only relevant for global prompts) */}
          {isGlobal && (
            <div className="space-y-1.5">
              <label className="text-xs font-medium text-slate-600 dark:text-slate-400">
                Excluded Agents
              </label>
              <p className="text-[10px] text-slate-400">
                Agent slugs that will NOT receive this global prompt.
              </p>
              <div className="flex flex-wrap gap-2 mb-2">
                {excludeAgents.map((agent) => (
                  <span
                    key={agent}
                    className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-mono bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 text-red-600 dark:text-red-400"
                  >
                    {agent}
                    <button
                      onClick={() =>
                        setExcludeAgents(excludeAgents.filter((a) => a !== agent))
                      }
                      className="ml-0.5 hover:text-red-800 dark:hover:text-red-200"
                    >
                      x
                    </button>
                  </span>
                ))}
              </div>
              <div className="flex gap-2">
                <input
                  type="text"
                  value={excludeInput}
                  onChange={(e) => setExcludeInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && excludeInput.trim()) {
                      e.preventDefault();
                      const val = excludeInput.trim();
                      if (!excludeAgents.includes(val)) {
                        setExcludeAgents([...excludeAgents, val]);
                      }
                      setExcludeInput("");
                    }
                  }}
                  placeholder="Agent slug..."
                  className="flex-1 px-3 py-2 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500/40"
                />
                <button
                  onClick={() => {
                    const val = excludeInput.trim();
                    if (val && !excludeAgents.includes(val)) {
                      setExcludeAgents([...excludeAgents, val]);
                    }
                    setExcludeInput("");
                  }}
                  disabled={!excludeInput.trim()}
                  className="px-3 py-2 text-sm font-medium rounded-lg bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors disabled:opacity-50"
                >
                  Add
                </button>
              </div>
            </div>
          )}

          <PromptRevisionHistory
            prompt={prompt}
            revisions={revisions}
            isLoading={revisionsLoading}
            restoringRevisionId={restoreMutation.isPending ? restoreMutation.variables ?? null : null}
            onRestore={(revisionId) => restoreMutation.mutate(revisionId)}
          />
        </div>
      </div>
    </div>
  );
}
