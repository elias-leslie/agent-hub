import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, CheckCircle2, RefreshCw, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { InheritedPlatformContextPreview } from "@/components/InheritedPlatformContextPreview";
import { Agent, AgentPreview, PreviewTaskType } from "../types";
import { PromptEditor } from "./PromptEditor";

interface PromptTabProps {
  formData: Partial<Agent>;
  preview: AgentPreview | undefined;
  previewFetching: boolean;
  showInlinePreview: boolean;
  setShowInlinePreview: (show: boolean) => void;
  previewMode: PreviewTaskType;
  setPreviewMode: (mode: PreviewTaskType) => void;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
  refetchPreview: () => void;
}

const PREVIEW_MODES: Array<{ value: PreviewTaskType; label: string }> = [
  { value: "chat", label: "Chat" },
  { value: "heartbeat", label: "Heartbeat" },
  { value: "wake", label: "Wake" },
  { value: "review", label: "Review" },
];

export function PromptTab({
  formData,
  preview,
  previewFetching,
  showInlinePreview,
  setShowInlinePreview,
  previewMode,
  setPreviewMode,
  updateField,
  refetchPreview,
}: PromptTabProps) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
          System Prompt
        </h2>
      </div>

      <InheritedPlatformContextPreview />

      <PromptEditor
        value={formData.system_prompt ?? ""}
        onChange={(v) => updateField("system_prompt", v)}
      />

      <div className="space-y-2">
        <label className="block text-sm font-medium text-slate-700 dark:text-slate-300">
          Runtime Preview Mode
        </label>
        <div className="flex flex-wrap gap-2">
          {PREVIEW_MODES.map((mode) => (
            <button
              key={mode.value}
              type="button"
              onClick={() => setPreviewMode(mode.value)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-sm transition-colors",
                previewMode === mode.value
                  ? "border-slate-900 bg-slate-900 text-white dark:border-slate-100 dark:bg-slate-100 dark:text-slate-900"
                  : "border-slate-200 text-slate-600 hover:border-slate-300 dark:border-slate-700 dark:text-slate-300"
              )}
            >
              {mode.label}
            </button>
          ))}
        </div>
      </div>

      <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
        <button
          onClick={() => {
            setShowInlinePreview(!showInlinePreview);
            if (!showInlinePreview) refetchPreview();
          }}
          className="w-full flex items-center justify-between px-4 py-3 bg-slate-50 dark:bg-slate-800/50 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          <div className="flex items-center gap-2">
            {showInlinePreview ? (
              <ChevronDown className="h-4 w-4 text-slate-500" />
            ) : (
              <ChevronRight className="h-4 w-4 text-slate-500" />
            )}
            <span className="text-sm font-medium text-slate-700 dark:text-slate-300">
              Combined Preview ({previewMode})
            </span>
            {preview && showInlinePreview && (
              <span className="text-xs text-slate-500 dark:text-slate-400 ml-2">
                {preview.mandate_count} mandates, {preview.guardrail_count} guardrails
              </span>
            )}
          </div>
          <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
            {showInlinePreview && (
              <>
                <button
                  onClick={() => refetchPreview()}
                  disabled={previewFetching}
                  className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                  title="Refresh preview"
                >
                  <RefreshCw className={cn("h-3.5 w-3.5 text-slate-500", previewFetching && "animate-spin")} />
                </button>
                <button
                  onClick={() => {
                    if (preview?.combined_prompt) {
                      navigator.clipboard.writeText(preview.combined_prompt);
                      setCopied(true);
                      setTimeout(() => setCopied(false), 2000);
                    }
                  }}
                  className="p-1.5 rounded hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
                  title="Copy combined prompt"
                >
                  {copied ? (
                    <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
                  ) : (
                    <Copy className="h-3.5 w-3.5 text-slate-500" />
                  )}
                </button>
              </>
            )}
          </div>
        </button>

        {showInlinePreview && (
          <div className="p-4 bg-slate-900 max-h-96 overflow-y-auto">
            {previewFetching && !preview ? (
              <div className="flex items-center justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-slate-400" />
              </div>
            ) : preview ? (
              <div className="space-y-4">
                {preview.task_prompt && (
                  <div className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                    <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500">
                      Task Prompt
                    </div>
                    <pre className="whitespace-pre-wrap text-xs font-mono text-slate-300 leading-relaxed">
                      {preview.task_prompt}
                    </pre>
                  </div>
                )}
                {preview.sections.map((section) => (
                  <div key={`${section.source_kind}:${section.source_id}:${section.content_hash}`} className="rounded-lg border border-slate-800 bg-slate-950 p-3">
                    <div className="mb-2 flex flex-wrap items-center gap-2 text-[11px] text-slate-500">
                      <span className="font-semibold uppercase tracking-[0.18em] text-slate-400">
                        {section.label}
                      </span>
                      <span>{section.source_kind}</span>
                      <span>{section.source_id}</span>
                      <span>{section.estimated_tokens} tok</span>
                      <span>{section.chars} ch</span>
                    </div>
                    <pre className="whitespace-pre-wrap text-xs font-mono text-slate-300 leading-relaxed">
                      {section.content}
                    </pre>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-sm text-slate-500 text-center py-4">
                Failed to load preview
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
