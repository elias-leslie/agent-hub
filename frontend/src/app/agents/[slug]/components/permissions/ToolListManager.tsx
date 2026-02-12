import { CheckCircle2, AlertTriangle, Plus, X } from "lucide-react";

interface ToolListManagerProps {
  allowList: string[];
  denyList: string[];
  newAllowTool: string;
  newDenyTool: string;
  onNewAllowToolChange: (value: string) => void;
  onNewDenyToolChange: (value: string) => void;
  onAddToAllowList: (tool: string) => void;
  onAddToDenyList: (tool: string) => void;
  onRemoveFromAllowList: (tool: string) => void;
  onRemoveFromDenyList: (tool: string) => void;
}

export function ToolListManager({
  allowList,
  denyList,
  newAllowTool,
  newDenyTool,
  onNewAllowToolChange,
  onNewDenyToolChange,
  onAddToAllowList,
  onAddToDenyList,
  onRemoveFromAllowList,
  onRemoveFromDenyList,
}: ToolListManagerProps) {
  return (
    <div className="space-y-6 pt-4 border-t border-slate-800">
      {/* Allow List */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="h-4 w-4 text-emerald-400" />
          <label className="text-sm font-medium text-slate-300">
            Allow List
          </label>
          <span className="text-xs text-slate-500">
            (auto-approve these tools)
          </span>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newAllowTool}
            onChange={(e) => onNewAllowToolChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAddToAllowList(newAllowTool)}
            placeholder="Tool name (e.g., read_file)"
            className="flex-1 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-emerald-500/50"
          />
          <button
            onClick={() => onAddToAllowList(newAllowTool)}
            className="px-3 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-sm font-medium flex items-center gap-1"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {allowList.map((tool) => (
            <span
              key={tool}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-emerald-950/40 border border-emerald-500/30 rounded-full text-sm text-emerald-300"
            >
              {tool}
              <button
                onClick={() => onRemoveFromAllowList(tool)}
                className="hover:text-emerald-100"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {allowList.length === 0 && (
            <span className="text-xs text-slate-500 italic">
              No tools in allow list
            </span>
          )}
        </div>
      </div>

      {/* Deny List */}
      <div className="space-y-3">
        <div className="flex items-center gap-2">
          <AlertTriangle className="h-4 w-4 text-red-400" />
          <label className="text-sm font-medium text-slate-300">
            Deny List
          </label>
          <span className="text-xs text-slate-500">
            (block these tools)
          </span>
        </div>
        <div className="flex gap-2">
          <input
            type="text"
            value={newDenyTool}
            onChange={(e) => onNewDenyToolChange(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAddToDenyList(newDenyTool)}
            placeholder="Tool name (e.g., bash)"
            className="flex-1 px-3 py-2 bg-slate-900 border border-slate-700 rounded-lg text-sm text-slate-200 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-red-500/50"
          />
          <button
            onClick={() => onAddToDenyList(newDenyTool)}
            className="px-3 py-2 bg-red-600 hover:bg-red-500 text-white rounded-lg text-sm font-medium flex items-center gap-1"
          >
            <Plus className="h-4 w-4" />
            Add
          </button>
        </div>
        <div className="flex flex-wrap gap-2">
          {denyList.map((tool) => (
            <span
              key={tool}
              className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-red-950/40 border border-red-500/30 rounded-full text-sm text-red-300"
            >
              {tool}
              <button
                onClick={() => onRemoveFromDenyList(tool)}
                className="hover:text-red-100"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
          {denyList.length === 0 && (
            <span className="text-xs text-slate-500 italic">
              No tools in deny list
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
