"use client";

import { MonitorDot } from "lucide-react";

export function SessionsTab() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <MonitorDot className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        Sessions
      </h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Sessions view coming soon
      </p>
    </div>
  );
}
