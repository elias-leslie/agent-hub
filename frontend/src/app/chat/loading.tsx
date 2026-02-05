import { Loader2 } from "lucide-react";

export default function ChatLoading() {
  return (
    <div className="h-full flex items-center justify-center bg-slate-50 dark:bg-slate-950">
      <div className="flex flex-col items-center gap-4">
        <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
        <p className="text-sm text-slate-500 dark:text-slate-400">Loading chat...</p>
      </div>
    </div>
  );
}
