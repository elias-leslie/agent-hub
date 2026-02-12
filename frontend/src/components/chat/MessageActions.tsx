import { Pencil, RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface MessageActionsProps {
  isUser: boolean;
  isStreaming: boolean;
  isEditing: boolean;
  isHovered: boolean;
  canEdit: boolean;
  canRegenerate: boolean;
  onEdit?: () => void;
  onRegenerate?: () => void;
}

export function MessageActions({
  isUser,
  isStreaming,
  isEditing,
  isHovered,
  canEdit,
  canRegenerate,
  onEdit,
  onRegenerate,
}: MessageActionsProps) {
  if (isStreaming) return null;

  // Assistant actions (left side)
  if (!isUser && onRegenerate && canRegenerate) {
    return (
      <div
        data-testid="message-actions"
        className={cn(
          "flex flex-col gap-1 pt-2 transition-opacity duration-200",
          isHovered ? "opacity-100" : "opacity-0"
        )}
      >
        <button
          data-testid="regenerate-btn"
          onClick={onRegenerate}
          className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          title="Regenerate response"
        >
          <RefreshCw className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  // User actions (right side)
  if (isUser && !isEditing && onEdit && canEdit) {
    return (
      <div
        className={cn(
          "flex flex-col gap-1 pt-2 transition-opacity duration-200",
          isHovered ? "opacity-100" : "opacity-0"
        )}
      >
        <button
          data-testid="edit-btn"
          onClick={onEdit}
          className="p-1.5 rounded-md hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 hover:text-slate-700 dark:hover:text-slate-300"
          title="Edit message"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return null;
}
