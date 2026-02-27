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
            ? "bg-blue-400 text-white placeholder-blue-200 focus:ring-blue-300"
            : "bg-gray-900 text-gray-100 focus:ring-blue-500"
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
              ? "hover:bg-blue-400 text-blue-100"
              : "hover:bg-gray-700 text-gray-500"
          )}
        >
          <X className="h-4 w-4" />
        </button>
        <button
          onClick={onSave}
          className={cn(
            "p-1 rounded",
            isUser
              ? "hover:bg-blue-400 text-white"
              : "hover:bg-gray-700 text-emerald-400"
          )}
        >
          <Check className="h-4 w-4" />
        </button>
      </div>
    </div>
  );
}
