import { Check, X } from "lucide-react";
import { cn } from "../lib/utils";

interface EditableContentProps {
  isUser: boolean;
  editContent: string;
  onContentChange: (content: string) => void;
  onSave: () => void;
  onCancel: () => void;
}

export function EditableContent({
  isUser,
  editContent,
  onContentChange,
  onSave,
  onCancel,
}: EditableContentProps) {
  return (
    <div className="space-y-2">
      <textarea
        value={editContent}
        onChange={(e) => onContentChange(e.target.value)}
        className={cn(
          "w-full min-w-[200px] px-2 py-1 rounded text-sm resize-none focus:outline-none focus:ring-2",
          isUser
            ? "bg-primary text-primary-foreground placeholder:text-primary-foreground/60 focus:ring-ring/30"
            : "border border-input bg-background text-foreground focus:ring-ring/20"
        )}
        rows={Math.min(editContent.split("\n").length + 1, 10)}
        autoFocus
      />
      <div className="flex gap-2 justify-end">
        <button
          onClick={onCancel}
          className={cn(
            "p-1 rounded",
            isUser
              ? "text-primary-foreground/80 hover:bg-primary/80"
              : "text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          )}
        >
          <X className="h-4 w-4" />
        </button>
        <button
          onClick={onSave}
          className={cn(
            "p-1 rounded",
            isUser
              ? "text-primary-foreground hover:bg-primary/80"
              : "text-emerald-500 hover:bg-accent"
          )}
        >
          <Check className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
