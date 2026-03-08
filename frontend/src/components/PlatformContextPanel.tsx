"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, Globe2, Save, Loader2, CheckCircle2, AlertCircle, Sparkles, Eye, EyeOff } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  PLATFORM_CONTEXT_PROMPT_SLUG,
  createPrompt,
  fetchOptionalPrompt,
  updatePrompt,
} from "@/lib/api/prompts";

async function fetchPlatformContext() {
  return fetchOptionalPrompt(PLATFORM_CONTEXT_PROMPT_SLUG);
}

function truncatePreview(content: string, maxLength = 120): string {
  if (!content) return "No platform context configured";
  const firstLine = content.split("\n")[0];
  return firstLine.length <= maxLength ? firstLine : firstLine.slice(0, maxLength).trim() + "…";
}

function usePlatformContext() {
  const queryClient = useQueryClient();
  const [editedContent, setEditedContent] = useState<string | null>(null);
  const [showSuccess, setShowSuccess] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["prompt", PLATFORM_CONTEXT_PROMPT_SLUG],
    queryFn: fetchPlatformContext,
  });

  const mutation = useMutation({
    mutationFn: async (payload: { content?: string; enabled?: boolean }) => {
      if (!data) {
        return createPrompt({
          slug: PLATFORM_CONTEXT_PROMPT_SLUG,
          name: "Platform Context",
          content: payload.content ?? "",
          description: "Platform-wide context injected into all agents as <platform_context>.",
          is_global: true,
          enabled: payload.enabled ?? true,
        });
      }
      return updatePrompt(PLATFORM_CONTEXT_PROMPT_SLUG, payload);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["prompt", PLATFORM_CONTEXT_PROMPT_SLUG] });
      queryClient.invalidateQueries({ queryKey: ["prompts"] });
      setEditedContent(null);
      setShowSuccess(true);
      setTimeout(() => setShowSuccess(false), 2000);
    },
  });

  useEffect(() => {
    if (editedContent === null) setEditedContent(data?.content ?? "");
  }, [data, editedContent]);

  const handleSave = useCallback(() => {
    if (editedContent !== null) mutation.mutate({ content: editedContent });
  }, [editedContent, mutation]);

  const handleToggleEnabled = useCallback(() => {
    mutation.mutate({ enabled: !(data?.enabled ?? true) });
  }, [data, mutation]);

  return {
    data,
    isLoading,
    error,
    editedContent,
    setEditedContent,
    hasChanges: editedContent !== null && editedContent !== (data?.content ?? ""),
    showSuccess,
    mutation,
    handleSave,
    handleToggleEnabled,
  };
}

function CollapsedHeader({ isExpanded, isEnabled, content, activeAgentCount, onToggle }: {
  isExpanded: boolean; isEnabled: boolean; content: string; activeAgentCount: number; onToggle: () => void;
}) {
  return (
    <button onClick={onToggle} className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-white/50 dark:hover:bg-slate-800/30 transition-colors">
      <div className="flex items-center gap-3 min-w-0">
        <div className={cn("flex items-center justify-center w-7 h-7 rounded-md transition-colors", isEnabled ? "bg-amber-100 dark:bg-amber-900/40" : "bg-slate-100 dark:bg-slate-800")}>
          <Globe2 className={cn("h-4 w-4", isEnabled ? "text-amber-600 dark:text-amber-400" : "text-slate-400")} />
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={cn("text-xs font-semibold uppercase tracking-wider", isEnabled ? "text-amber-700 dark:text-amber-300" : "text-slate-500")}>Platform Context</span>
            {!isEnabled && <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase tracking-wider rounded bg-slate-200 dark:bg-slate-700 text-slate-500 dark:text-slate-400">Disabled</span>}
          </div>
          <p className="text-xs text-slate-500 dark:text-slate-400 truncate mt-0.5">{truncatePreview(content)}</p>
        </div>
      </div>
      <div className="flex items-center gap-3 flex-shrink-0 ml-4">
        <div className="hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-white/60 dark:bg-slate-800/60 border border-slate-200/60 dark:border-slate-700/60">
          <Sparkles className="h-3 w-3 text-slate-400" />
          <span className="text-[10px] font-medium text-slate-600 dark:text-slate-400">{activeAgentCount} agent{activeAgentCount !== 1 ? "s" : ""}</span>
        </div>
        <div className="flex items-center justify-center w-6 h-6 rounded bg-white/60 dark:bg-slate-800/60">
          {isExpanded ? <ChevronDown className="h-4 w-4 text-slate-400" /> : <ChevronRight className="h-4 w-4 text-slate-400" />}
        </div>
      </div>
    </button>
  );
}

function Toolbar({ isEnabled, hasChanges, showSuccess, isPending, onToggle, onSave }: {
  isEnabled: boolean; hasChanges: boolean; showSuccess: boolean; isPending: boolean; onToggle: () => void; onSave: () => void;
}) {
  return (
    <div className="flex items-center justify-between py-3">
      <p className="text-[10px] uppercase tracking-wider text-slate-400">DB-backed global prompt injected into all agents</p>
      <div className="flex items-center gap-2">
        <button onClick={(e) => { e.stopPropagation(); onToggle(); }} disabled={isPending} className={cn("flex items-center gap-1.5 px-2.5 py-1.5 rounded-md text-xs font-medium transition-colors", isEnabled ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-900/50" : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700")}>
          {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : isEnabled ? <Eye className="h-3.5 w-3.5" /> : <EyeOff className="h-3.5 w-3.5" />}
          {isEnabled ? "Enabled" : "Disabled"}
        </button>
        <button onClick={(e) => { e.stopPropagation(); onSave(); }} disabled={!hasChanges || isPending} className={cn("flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-semibold transition-all", hasChanges ? "bg-amber-500 text-white hover:bg-amber-600 shadow-sm" : "bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-not-allowed")}>
          {isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : showSuccess ? <CheckCircle2 className="h-3.5 w-3.5" /> : <Save className="h-3.5 w-3.5" />}
          {showSuccess ? "Saved" : "Save"}
        </button>
      </div>
    </div>
  );
}

function Editor({ content, isEnabled, onChange }: { content: string; isEnabled: boolean; onChange: (value: string) => void; }) {
  return (
    <div className="relative">
      <textarea value={content} onChange={(e) => onChange(e.target.value)} placeholder="Enter platform-wide context shared by all agents..." rows={8} className={cn("w-full px-4 py-3 rounded-lg border text-sm font-mono leading-relaxed resize-y focus:outline-none focus:ring-2 transition-colors min-h-[150px] max-h-[calc(100vh-20rem)]", isEnabled ? "bg-white dark:bg-slate-900 border-amber-200 dark:border-amber-900/50 focus:ring-amber-500/30 focus:border-amber-400" : "bg-slate-50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 focus:ring-slate-500/30 text-slate-500")} />
      <div className="absolute bottom-2 right-2">
        <span className="text-[10px] font-mono text-slate-400 bg-white/80 dark:bg-slate-900/80 px-1.5 py-0.5 rounded">{content.length.toLocaleString()} chars</span>
      </div>
    </div>
  );
}

export function PlatformContextPanel({ activeAgentCount }: { activeAgentCount: number }) {
  const [isExpanded, setIsExpanded] = useState(false);
  const { data, isLoading, error, editedContent, setEditedContent, hasChanges, showSuccess, mutation, handleSave, handleToggleEnabled } = usePlatformContext();

  if (isLoading) return <div className="mb-5"><div className="h-12 rounded-lg bg-slate-100 dark:bg-slate-800/50 animate-pulse" /></div>;

  if (error) {
    return (
      <div className="mb-5 flex items-center gap-2 px-4 py-3 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400">
        <AlertCircle className="h-4 w-4 flex-shrink-0" />
        <span className="text-xs">Failed to load platform context</span>
      </div>
    );
  }

  const content = editedContent ?? data?.content ?? "";
  const isEnabled = data?.enabled ?? true;

  return (
    <div className="mb-5">
      <div className={cn("rounded-lg border overflow-hidden transition-all duration-200", isEnabled ? "border-amber-300/50 dark:border-amber-700/50 bg-gradient-to-r from-amber-50/80 via-amber-50/40 to-transparent dark:from-amber-950/30 dark:via-amber-950/10 dark:to-transparent" : "border-slate-200 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50")}>
        <CollapsedHeader isExpanded={isExpanded} isEnabled={isEnabled} content={content} activeAgentCount={activeAgentCount} onToggle={() => setIsExpanded(!isExpanded)} />
        {isExpanded && (
          <div className="px-4 pb-4 border-t border-slate-200/50 dark:border-slate-700/50">
            <Toolbar isEnabled={isEnabled} hasChanges={hasChanges} showSuccess={showSuccess} isPending={mutation.isPending} onToggle={handleToggleEnabled} onSave={handleSave} />
            <Editor content={content} isEnabled={isEnabled} onChange={setEditedContent} />
            <div className="mt-3 flex items-start gap-2 text-[10px] text-slate-400">
              <div className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600 mt-1.5 flex-shrink-0" />
              <p>This is the canonical DB-backed prompt injected into every agent as <code className="px-1 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-mono">&lt;platform_context&gt;</code>. Review it in the Prompts UI or any agent&apos;s combined preview.</p>
            </div>
          </div>
        )}
      </div>
      {mutation.isError && (
        <div className="mt-2 flex items-center gap-2 px-3 py-2 rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-900 text-red-600 dark:text-red-400">
          <AlertCircle className="h-3.5 w-3.5 flex-shrink-0" />
          <span className="text-xs">Failed to save changes</span>
        </div>
      )}
    </div>
  );
}
