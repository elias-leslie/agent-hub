import { useState } from "react";
import { ChevronDown, ChevronRight, Copy, CheckCircle2, RefreshCw, Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { InheritedContextPreview } from "@/components/InheritedContextPreview";
import { Agent, AgentPreview } from "../types";
import { PromptEditor } from "./PromptEditor";

interface PromptTabProps {
  formData: Partial<Agent>;
  preview: AgentPreview | undefined;
  previewFetching: boolean;
  showInlinePreview: boolean;
  setShowInlinePreview: (show: boolean) => void;
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void;
  refetchPreview: () => void;
}

export function PromptTab({ formData, preview, previewFetching, showInlinePreview, setShowInlinePreview, updateField, refetchPreview }: PromptTabProps) {
  const [copied, setCopied] = useState(false);

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-4">
          System Prompt
        </h2>
      </div>

      <InheritedContextPreview />

      <PromptEditor
        value={formData.system_prompt ?? ""}
        onChange={(v) => updateField("system_prompt", v)}
      />

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
              Combined Preview (with Memory)
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
              <pre className="whitespace-pre-wrap text-xs font-mono text-slate-300 leading-relaxed">
                {preview.combined_prompt.split('\n').map((line, i) => {
                  if (line.startsWith('- [M:')) {
                    return <span key={i} className="text-blue-400">{line}{'\n'}</span>;
                  } else if (line.startsWith('- [G:')) {
                    return <span key={i} className="text-amber-400">{line}{'\n'}</span>;
                  } else if (line.startsWith('## Mandates')) {
                    return <span key={i} className="text-blue-500 font-semibold">{line}{'\n'}</span>;
                  } else if (line.startsWith('## Guardrails')) {
                    return <span key={i} className="text-amber-500 font-semibold">{line}{'\n'}</span>;
                  }
                  return <span key={i}>{line}{'\n'}</span>;
                })}
              </pre>
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
