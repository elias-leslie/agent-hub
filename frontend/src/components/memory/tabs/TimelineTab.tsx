"use client";

import { Clock } from "lucide-react";

export function TimelineTab() {
  return (
    <div className="flex flex-col items-center justify-center py-24 text-center">
      <div className="p-4 rounded-full bg-slate-800 mb-4">
        <Clock className="w-8 h-8 text-slate-400" />
      </div>
      <h3 className="text-lg font-medium text-slate-100 mb-1">
        Timeline
      </h3>
      <p className="text-sm text-slate-400 max-w-sm">
        Timeline view coming soon
      </p>
    </div>
  );
}
