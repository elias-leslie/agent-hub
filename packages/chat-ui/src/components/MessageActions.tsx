import { Pencil, RefreshCw, CornerDownRight } from "lucide-react";
import { cn } from "../lib/utils";

interface MessageActionsProps {
  isUser: boolean;
  isStreaming: boolean;
  isEditing: boolean;
  isHovered: boolean;
  canEdit: boolean;
  canRegenerate: boolean;
  canContinue?: boolean;
  onEdit?: () => void;
  onRegenerate?: () => void;
  onContinue?: () => void;
}

export function MessageActions({
  isUser,
  isStreaming,
  isEditing,
  isHovered,
  canEdit,
  canRegenerate,
  canContinue = false,
  onEdit,
  onRegenerate,
  onContinue,
}: MessageActionsProps) {
  if (isStreaming) return null;

  // Assistant actions (left side)
  if (!isUser && ((onRegenerate && canRegenerate) || (onContinue && canContinue))) {
    return (
      <div
        data-testid="message-actions"
        className={cn(
          "flex flex-col gap-1 pt-2 transition-opacity duration-200",
          isHovered ? "opacity-100" : "opacity-0"
        )}
      >
        {onRegenerate && canRegenerate ? (
          <button
            data-testid="regenerate-btn"
            onClick={onRegenerate}
            className="p-1.5 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Regenerate response"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        ) : null}
        {onContinue && canContinue ? (
          <button
            data-testid="continue-btn"
            onClick={onContinue}
            className="p-1.5 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
            title="Continue response"
          >
            <CornerDownRight className="h-3.5 w-3.5" />
          </button>
        ) : null}
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
          className="p-1.5 rounded-md text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          title="Edit message"
        >
          <Pencil className="h-3.5 w-3.5" />
        </button>
      </div>
    );
  }

  return null;
}
