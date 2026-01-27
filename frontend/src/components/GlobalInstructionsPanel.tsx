"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  ChevronDown,
  ChevronRight,
  Globe2,
  Save,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Sparkles,
  Eye,
  EyeOff,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { fetchApi } from "@/lib/api-config";

interface GlobalInstructions {
  id: string;
  content: string;
  enabled: boolean;
  updated_at: string;
  applied_to_count: number;
}

async function fetchGlobalInstructions(): Promise<GlobalInstructions> {
  const res = await fetchApi("/api/global-instructions");
  if (!res.ok) {
    if (res.status === 404) {
      return {
        id: "",
        content: "",
        enabled: true,
        updated_at: new Date().toISOString(),
        applied_to_count: 0,
      };
    }
    throw new Error("Failed to fetch global instructions");
  }
  return res.json();
}

async function updateGlobalInstructions(
  data: Partial<GlobalInstructions>
): Promise<GlobalInstructions> {
  const res = await fetchApi("/api/global-instructions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update global instructions");
  return res.json();
}

function truncatePreview(content: string, maxLength: number = 120): string {
  if (!content) return "No global instructions configured";
  const firstLine = content.split("\n")[0];
  if (firstLine.length <= maxLength) return firstLine;
  return firstLine.slice(0, maxLength).trim() + "…";
}

export function GlobalInstructionsPanel({
  activeAgentCount,
}: {
  activeAgentCount: number;
}) {
  const queryClient = useQueryClient();
  const [isExpanded, setIsExpanded] = useState(false);
  const [editedContent, setEditedContent] = useState<string | null>(null);
  const [showSuccess, setShowSuccess] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["global-instructions"],
    queryFn: fetchGlobalInstructions,
  });

  const mutation = useMutation({
    mutationFn: updateGlobalInstructions,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["global-instructions"] });
      setEditedContent(null);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 2000);
    },
  });

  const toggleMutation = useMutation({
    mutationFn: (enabled: boolean) => updateGlobalInstructions({ enabled }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["global-instructions"] });
    },
  });

  useEffect(() => {
    if (data && editedContent === null) {
      setEditedContent(data.content);
    }
  }, [data, editedContent]);

  const hasChanges = editedContent !== null && editedContent !== data?.content;

  const handleSave = useCallback(() => {
    if (editedContent !== null) {
      mutation.mutate({ content: editedContent });
    }
  }, [editedContent, mutation]);

  const handleToggleEnabled = useCallback(() => {
    if (data) {
      toggleMutation.mutate(!data.enabled);
    }
  }, [data, toggleMutation]);

  if (isLoading) {
    return (
      <div className="mb-5">
        <div className="h-12 rounded-lg bg-slate-100 dark:bg-slate-800/50 animate-pulse" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="mb-5 flex items-center gap-2 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400">
        <AlertCircle className="h-4 w-4 flex-shrink-0" />
        <span className="text-xs">Failed to load global instructions</span>
      </div>
    );
  }

  const content = editedContent ?? data?.content ?? "";
  const isEnabled = data?.enabled ?? true;

  return (
    <div className="mb-5">
      <div
        className={cn(
          "rounded-lg border overflow-hidden transition-all duration-200",
          isEnabled
            ? "border-amber-300/50 dark:border-amber-700/50 bg-gradient-to-r from-amber-50/80 via-amber-50/40 to-transparent dark:from-amber-950/30 dark:via-amber-950/10 dark:to-transparent"
            : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50"
        )}
      >
        {/* Collapsed Header */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/50 dark:hover:bg-slate-800/30 transition-colors"
        >
          <div className="flex items-center gap-3 min-w-0">
            <div
              className={cn(
                "flex items-center justify-center w-7 h-7 rounded-md transition-colors",
                isEnabled
                  ? "bg-amber-100 dark:bg-amber-900/40"
                  : "bg-slate-100 dark:bg-slate-800"
              )}
            >
              <Globe2
                className={cn(
                  "h-4 w-4",
                  isEnabled
                    ? "text-amber-600 dark:text-amber-400"
                    : "text-slate-400"
                )}
              />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span
                  className={cn(
                    "text-xs font-semibold uppercase tracking-wider",
                    isEnabled
                      ? "text-amber-700 dark:text-amber-300"
                      : "text-slate-500"
                  )}
                >
                  Global Instructions
                </span>
                {!isEnabled && (
                  <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400">
                    Disabled
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">
                {truncatePreview(content)}
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3 flex-shrink-0 ml-4">
            {/* Applied to count */}
            <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/60 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/60">
              <Sparkles className="h-3 w-3 text-slate-400" />
              <span className="text-[10px] font-medium text-slate-600 dark:text-slate-400">
                {activeAgentCount} agent{activeAgentCount !== 1 ? "s" : ""}
              </span>
            </div>

            {/* Expand indicator */}
            <div className="flex items-center justify-center w-6 h-6 rounded bg-white/60 dark:bg-slate-800/60">
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-slate-400" />
              ) : (
                <ChevronRight className="h-4 w-4 text-slate-400" />
              )}
            </div>
          </div>
        </button>

        {/* Expanded Content */}
        {isExpanded && (
          <div className="px-4 pb-4 border-t border-slate-200/50 dark:border-slate-700/50">
            {/* Toolbar */}
            <div className="flex items-center justify-between py-3">
              <div className="flex items-center gap-3">
                <p className="text-[10px] uppercase tracking-wider text-slate-400">
                  Platform-wide context injected into all agents
                </p>
              </div>
              <div className="flex items-center gap-2">
                {/* Enable/Disable toggle */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleToggleEnabled();
                  }}
                  disabled={toggleMutation.isPending}
                  className={cn(
                    "flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors",
                    isEnabled
                      ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
                  )}
                >
                  {toggleMutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : isEnabled ? (
                    <Eye className="h-3.5 w-3.5" />
                  ) : (
                    <EyeOff className="h-3.5 w-3.5" />
                  )}
                  {isEnabled ? "Enabled" : "Disabled"}
                </button>

                {/* Save button */}
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    handleSave();
                  }}
                  disabled={!hasChanges || mutation.isPending}
                  className={cn(
                    "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all",
                    hasChanges
                      ? "bg-amber-500 text-white hover:bg-amber-600 shadow-sm"
                      : "bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-not-allowed"
                  )}
                >
                  {mutation.isPending ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : showSuccess ? (
                    <CheckCircle2 className="h-3.5 w-3.5" />
                  ) : (
                    <Save className="h-3.5 w-3.5" />
                  )}
                  {showSuccess ? "Saved" : "Save"}
                </button>
              </div>
            </div>

            {/* Editor */}
            <div className="relative">
              <textarea
                value={content}
                onChange={(e) => setEditedContent(e.target.value)}
                placeholder="Enter global instructions that apply to all agents...

Examples:
- Always respond in a professional tone
- Include source citations when available
- Follow company style guidelines
- Prioritize security best practices"
                rows={8}
                className={cn(
                  "w-full px-4 py-3 rounded-lg border text-sm font-mono leading-relaxed resize-y focus:outline-none focus:ring-2 transition-colors",
                  isEnabled
                    ? "bg-white dark:bg-slate-900 border-amber-200 dark:border-amber-900/50 focus:ring-amber-500/30 focus:border-amber-400"
                    : "bg-slate-50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 focus:ring-slate-500/30 text-slate-500"
                )}
              />
              <div className="absolute bottom-2 right-2 flex items-center gap-2">
                <span className="text-[10px] font-mono text-slate-400 bg-white/80 dark:bg-slate-900/80 px-1.5 py-0.5 rounded">
                  {content.length.toLocaleString()} chars
                </span>
              </div>
            </div>

            {/* Help text */}
            <div className="mt-3 flex items-start gap-2 text-[10px] text-slate-400">
              <div className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600 mt-1.5 flex-shrink-0" />
              <p>
                These instructions are prepended to every agent&apos;s system
                prompt as{" "}
                <code className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">
                  &lt;platform_context&gt;
                </code>{" "}
                block. View the combined prompt on any agent&apos;s Prompt tab.
              </p>
            </div>
          </div>
        )}
      </div>

      {/* Mutation error */}
      {mutation.isError && (
        <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="text-xs">Failed to save changes</span>
        </div>
      )}
    </div>
  );
}
