import { useState } from "react";
import { Terminal } from "lucide-react";
import type { ToolExecution } from "@/types/chat";
import { ToolExecutionItem } from "./ToolExecutionItem";

/**
 * Display all tool executions for a message.
 */
export function ToolExecutionDisplay({ tools }: { tools: ToolExecution[] }) {
  const [showAll, setShowAll] = useState(false);
  const displayTools = showAll ? tools : tools.slice(0, 3);
  const hasMore = tools.length > 3;

  return (
    <div className="mb-3 space-y-1.5">
      <div className="flex items-center gap-1.5 text-xs text-slate-500 dark:text-slate-400 mb-1">
        <Terminal className="h-3.5 w-3.5" />
        <span className="font-medium">Tool Executions ({tools.length})</span>
      </div>
      <div className="space-y-1">
        {displayTools.map((tool) => (
          <ToolExecutionItem key={tool.id} tool={tool} />
        ))}
      </div>
      {hasMore && (
        <button
          onClick={() => setShowAll(!showAll)}
          className="text-xs text-blue-600 dark:text-blue-400 hover:underline"
        >
          {showAll ? "Show less" : `Show ${tools.length - 3} more...`}
        </button>
      )}
    </div>
  );
}
