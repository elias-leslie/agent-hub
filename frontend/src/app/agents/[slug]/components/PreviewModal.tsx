import { X, Loader2 } from "lucide-react";
import { AgentPreview, PreviewTaskType } from "../types";

interface PreviewModalProps {
  preview: AgentPreview | undefined;
  previewMode: PreviewTaskType;
  onClose: () => void;
}

export function PreviewModal({ preview, previewMode, onClose }: PreviewModalProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white dark:bg-slate-900 rounded-xl shadow-xl w-full max-w-3xl max-h-[80vh] overflow-hidden">
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-200 dark:border-slate-700">
          <div>
            <h3 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Combined Prompt Preview
            </h3>
            {preview ? (
              <p className="text-xs text-slate-500">
                {previewMode} mode, {preview.mandate_count} mandates, {preview.guardrail_count} guardrails
              </p>
            ) : null}
          </div>
          <button
            onClick={onClose}
            className="p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="h-5 w-5" />
          </button>
        </div>
        <div className="p-6 overflow-y-auto max-h-[60vh]">
          {preview ? (
            <div className="space-y-4">
              <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Memory Query
                </div>
                <pre className="whitespace-pre-wrap text-sm font-mono text-slate-700 dark:text-slate-300">
                  {preview.memory_query || "(empty)"}
                </pre>
              </div>
              <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Loaded Memory UUIDs
                </div>
                <pre className="whitespace-pre-wrap break-all text-sm font-mono text-slate-700 dark:text-slate-300">
                  {preview.loaded_memory_uuids.length > 0
                    ? preview.loaded_memory_uuids.join("\n")
                    : "(none)"}
                </pre>
              </div>
              {preview.sections.map((section) => (
                <div
                  key={`${section.source_kind}:${section.source_id}:${section.content_hash}`}
                  className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800"
                >
                  <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-slate-500">
                    <span className="font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
                      {section.label}
                    </span>
                    <span>{section.placement}</span>
                    <span>{section.source_kind}</span>
                    <span>{section.source_id}</span>
                    <span>{section.estimated_tokens} tok</span>
                  </div>
                  <pre className="whitespace-pre-wrap text-sm font-mono text-slate-700 dark:text-slate-300">
                    {section.content}
                  </pre>
                </div>
              ))}
              <div className="rounded-lg bg-slate-50 p-4 dark:bg-slate-800">
                <div className="mb-2 text-xs font-semibold uppercase tracking-[0.18em] text-slate-500">
                  Full Context
                </div>
                <pre className="whitespace-pre-wrap text-sm font-mono text-slate-700 dark:text-slate-300">
                  {preview.full_context || preview.combined_prompt}
                </pre>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-6 w-6 animate-spin text-slate-400" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
