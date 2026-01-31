import { Ban, Play, Trash2, RefreshCw, Pencil } from "lucide-react";
import { cn } from "@/lib/utils";

interface ActionButtonsProps {
  clientStatus: string;
  onEdit: () => void;
  onRotateSecret: () => void;
  onSuspend: () => void;
  onActivate: () => void;
  onBlock: () => void;
  isRotating: boolean;
  isActivating: boolean;
}

export function ActionButtons({
  clientStatus,
  onEdit,
  onRotateSecret,
  onSuspend,
  onActivate,
  onBlock,
  isRotating,
  isActivating,
}: ActionButtonsProps) {
  return (
    <div className="bg-slate-900/60 border border-slate-800 rounded-xl p-6">
      <h2 className="text-sm font-semibold text-slate-300 mb-4">Actions</h2>
      <div className="flex flex-wrap gap-3">
        <button
          onClick={onEdit}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 text-sm transition-colors"
        >
          <Pencil className="h-4 w-4" />
          Edit Settings
        </button>

        <button
          onClick={onRotateSecret}
          disabled={isRotating}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-100 text-sm transition-colors disabled:opacity-50"
        >
          <RefreshCw className={cn("h-4 w-4", isRotating && "animate-spin")} />
          Rotate Secret
        </button>

        {clientStatus === "active" && (
          <button
            onClick={onSuspend}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600/20 hover:bg-amber-600/30 text-amber-300 text-sm transition-colors"
          >
            <Ban className="h-4 w-4" />
            Suspend
          </button>
        )}

        {clientStatus === "suspended" && (
          <button
            onClick={onActivate}
            disabled={isActivating}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 text-sm transition-colors disabled:opacity-50"
          >
            <Play className="h-4 w-4" />
            Activate
          </button>
        )}

        {clientStatus !== "blocked" && (
          <button
            onClick={onBlock}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-red-600/20 hover:bg-red-600/30 text-red-300 text-sm transition-colors"
          >
            <Trash2 className="h-4 w-4" />
            Block Permanently
          </button>
        )}
      </div>
    </div>
  );
}
