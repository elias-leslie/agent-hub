import { AlertCircle } from "lucide-react";

export function ErrorAlert() {
  return (
    <div className="flex items-center gap-2 p-4 rounded-lg bg-red-900/20 border border-red-800 text-red-400 mb-5">
      <AlertCircle className="h-4 w-4" />
      <p className="text-xs font-medium">Failed to load sessions</p>
    </div>
  );
}
