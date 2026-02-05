"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Dashboard error:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-slate-950">
      <div className="fixed inset-0 bg-grid-pattern pointer-events-none opacity-30" />

      <header className="sticky top-0 z-20 border-b border-slate-800/80 bg-slate-900/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8 h-12 flex items-center">
          <h1 className="text-base font-semibold text-slate-100">Dashboard</h1>
        </div>
      </header>

      <main className="relative px-6 lg:px-8 py-5">
        <div className="flex flex-col items-center justify-center py-20">
          <div className="p-4 rounded-full bg-red-900/20 mb-4">
            <AlertTriangle className="h-8 w-8 text-red-500" />
          </div>
          <h2 className="text-lg font-semibold text-slate-100 mb-2">
            Failed to load dashboard
          </h2>
          <p className="text-sm text-slate-400 mb-6 text-center max-w-md">
            Unable to fetch dashboard data. This might be a temporary issue with the backend.
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
