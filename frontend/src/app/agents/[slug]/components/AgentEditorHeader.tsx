import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bot, Save, ArrowLeft, Eye, MessageSquare, Loader2, Menu, FlaskConical } from "lucide-react";
import { Agent } from "../types";

interface AgentEditorHeaderProps {
  agent: Agent;
  hasChanges: boolean;
  isSaving: boolean;
  onSave: () => void;
  onPreview: () => void;
  onOpenSidebar?: () => void;
  activeTabLabel?: string;
}

export function AgentEditorHeader({
  agent,
  hasChanges,
  isSaving,
  onSave,
  onPreview,
  onOpenSidebar,
  activeTabLabel,
}: AgentEditorHeaderProps) {
  const router = useRouter();

  return (
    <header className="sticky top-0 z-30 border-b border-slate-800 bg-slate-900/95 backdrop-blur-sm">
      <div className="px-4 lg:px-8">
        <div className="flex min-h-14 flex-col gap-3 py-3 lg:h-14 lg:flex-row lg:items-center lg:justify-between lg:py-0">
          <div className="flex items-center gap-3 lg:gap-4">
            <button
              type="button"
              onClick={onOpenSidebar}
              aria-label="Open editor sections"
              className="rounded-lg p-1.5 text-slate-600 transition-colors hover:bg-slate-100 dark:text-slate-400 dark:hover:bg-slate-800 lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            <button
              type="button"
              onClick={() => router.push("/agents")}
              aria-label="Back to agents"
              className="p-1.5 rounded-lg hover:bg-slate-800 transition-colors"
            >
              <ArrowLeft className="h-5 w-5 text-slate-400" />
            </button>
            <div className="min-w-0">
              <div className="flex items-center gap-2 min-w-0">
                <Bot className="h-5 w-5 shrink-0 text-slate-400" />
                <h1 className="truncate text-lg font-bold tracking-tight text-slate-100">
                  {agent.name}
                </h1>
                <span className="rounded bg-slate-100 px-2 py-0.5 text-xs font-mono text-slate-400 dark:bg-slate-800">
                  {agent.slug}
                </span>
              </div>
              {activeTabLabel && (
                <p className="mt-1 text-xs text-slate-400 lg:hidden">
                  {activeTabLabel}
                </p>
              )}
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {hasChanges && (
              <span className="text-xs text-amber-600 dark:text-amber-400">
                Unsaved changes
              </span>
            )}
            <button
              type="button"
              onClick={onPreview}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <Eye className="h-3.5 w-3.5" />
              Preview
            </button>
            <Link
              href={`/agents/${agent.slug}/chat`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <MessageSquare className="h-3.5 w-3.5" />
              Chat
            </Link>
            <Link
              href={`/arena/${agent.slug}`}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors"
            >
              <FlaskConical className="h-3.5 w-3.5" />
              Arena
            </Link>
            <button
              type="button"
              onClick={onSave}
              disabled={!hasChanges || isSaving}
              className="flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50 transition-colors"
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
