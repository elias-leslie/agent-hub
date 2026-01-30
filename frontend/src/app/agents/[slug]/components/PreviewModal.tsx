import { X, Loader2 } from "lucide-react";
import { AgentPreview } from "../types";

interface PreviewModalProps {
  preview: AgentPreview | undefined;
  onClose: () => void;
}

export function PreviewModal({ preview, onClose }: PreviewModalProps) {
  return (
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
            onClick={onClose}
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
  );
}
