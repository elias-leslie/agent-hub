"use client";

import { useEffect } from "react";
import { AlertTriangle, RefreshCw, Shield } from "lucide-react";

export default function AdminError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Admin error:", error);
  }, [error]);

  return (
    <div className="min-h-screen bg-slate-950">
      <header className="sticky top-0 z-20 border-b border-slate-800 bg-slate-950/90 backdrop-blur-xl">
        <div className="px-6 lg:px-8">
          <div className="flex items-center gap-4 h-16">
            <div className="p-2.5 rounded-xl bg-gradient-to-br from-amber-500/20 to-orange-600/20 border border-amber-500/30">
              <Shield className="w-6 h-6 text-amber-400" />
            </div>
            <h1 className="text-xl font-bold text-slate-100">Usage Control</h1>
          </div>
        </div>
      </header>

      <main className="px-6 lg:px-8 py-8">
        <div className="flex flex-col items-center justify-center py-20">
          <div className="p-4 rounded-full bg-red-900/20 mb-4">
            <AlertTriangle className="h-8 w-8 text-red-500" />
          </div>
          <h2 className="text-lg font-semibold text-slate-100 mb-2">
            Failed to load admin panel
          </h2>
          <p className="text-sm text-slate-400 mb-6 text-center max-w-md">
            Unable to fetch kill switch data. Please try again.
          </p>
          <button
            onClick={reset}
            className="flex items-center gap-2 px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white font-medium transition-colors"
          >
            <RefreshCw className="h-4 w-4" />
            Try again
          </button>
        </div>
      </main>
    </div>
  );
}
