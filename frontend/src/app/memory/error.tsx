"use client";

import { useEffect } from "react";
import { AlertCircle, RefreshCw, Brain } from "lucide-react";

export default function MemoryError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Memory error:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      <header className="sticky top-0 z-30 border-b border-slate-200 dark:border-slate-800 bg-white/95 dark:bg-slate-900/95 backdrop-blur-sm">
        <div className="px-4 lg:px-6">
          <div className="flex items-center gap-2 h-14">
            <div className="p-1.5 rounded-lg bg-emerald-100 dark:bg-emerald-900/30">
              <Brain className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            </div>
            <h1 className="text-lg font-bold text-slate-900 dark:text-slate-100">
              Memory
            </h1>
          </div>
        </div>
      </header>

      <main className="px-4 lg:px-6 py-5">
        <div className="flex flex-col items-center justify-center py-20">
          <div className="p-4 rounded-full bg-red-100 dark:bg-red-900/20 mb-4">
            <AlertCircle className="h-8 w-8 text-red-500" />
          </div>
          <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100 mb-2">
            Failed to load memory
          </h2>
          <p className="text-sm text-slate-600 dark:text-slate-400 mb-6 text-center max-w-md">
            Unable to fetch memory data. The memory service might be unavailable.
          </p>
          <button
            onClick={reset}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white font-medium transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Try again
          </button>
        </div>
      </main>
    </div>
  );
}
