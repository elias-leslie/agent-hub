import { useRouter } from "next/navigation";
import { Bot, Save, ArrowLeft, Eye, Play, Loader2 } from "lucide-react";
import { Agent } from "../types";

interface AgentEditorHeaderProps {
  agent: Agent;
  hasChanges: boolean;
  isSaving: boolean;
  onSave: () => void;
  onPreview: () => void;
}

export function AgentEditorHeader({
  agent,
  hasChanges,
  isSaving,
  onSave,
  onPreview,
}: AgentEditorHeaderProps) {
  const router = useRouter();

  return (
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
              onClick={onPreview}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <Eye className="h-3.5 w-3.5" />
              Preview
            </button>
            <a
              href={`/agents/${agent.slug}/playground`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <Play className="h-3.5 w-3.5" />
              Playground
            </a>
            <button
              onClick={onSave}
              disabled={!hasChanges || isSaving}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
            >
              {isSaving ? (
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
  );
}
