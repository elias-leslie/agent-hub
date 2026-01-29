import { ArrowLeft, Bot, Trash2 } from "lucide-react";
import type { Agent } from "../types";

interface PlaygroundHeaderProps {
  agent: Agent;
  selectedSlug: string;
  initialSlug: string;
  agents: Agent[] | undefined;
  onBack: () => void;
  onSelectAgent: (slug: string) => void;
  onClearChat: () => void;
}

export function PlaygroundHeader({
  agent,
  selectedSlug,
  initialSlug,
  agents,
  onBack,
  onSelectAgent,
  onClearChat,
}: PlaygroundHeaderProps) {
  return (
    <header className="flex-shrink-0 border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
      <div className="px-4 h-14 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <button
            onClick={onBack}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <ArrowLeft className="h-5 w-5 text-slate-600 dark:text-slate-400" />
          </button>

          <div className="flex items-center gap-3">
            <Bot className="h-5 w-5 text-slate-600 dark:text-slate-400" />
            <span className="text-sm font-semibold text-slate-700 dark:text-slate-300">
              Playground
            </span>

            <select
              value={selectedSlug}
              onChange={(e) => onSelectAgent(e.target.value)}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-blue-500/40"
            >
              {agents?.map((a) => (
                <option key={a.slug} value={a.slug}>
                  {a.name}
                </option>
              ))}
            </select>
          </div>
        </div>

        <button
          onClick={onClearChat}
          className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
        >
          <Trash2 className="h-3.5 w-3.5" />
          Clear
        </button>
      </div>
    </header>
  );
}
