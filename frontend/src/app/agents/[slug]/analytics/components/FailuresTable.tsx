import { Zap, ExternalLink } from "lucide-react";
import type { AnalyticsData } from "../types";

interface FailuresTableProps {
  failures: AnalyticsData["recent_failures"];
}

export function FailuresTable({ failures }: FailuresTableProps) {
  if (failures.length === 0) {
    return (
      <div className="py-8 text-center">
        <div className="w-12 h-12 rounded-full bg-emerald-50 dark:bg-emerald-950/30 flex items-center justify-center mx-auto mb-3">
          <Zap className="h-6 w-6 text-emerald-500" />
        </div>
        <p className="text-sm text-slate-500 dark:text-slate-400">
          No failures in the selected time range
        </p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-700">
            <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
              Time
            </th>
            <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
              Error Type
            </th>
            <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
              Message
            </th>
            <th className="text-left text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
              Model
            </th>
            <th className="text-right text-[10px] font-bold uppercase tracking-wider text-slate-500 py-2">
              Action
            </th>
          </tr>
        </thead>
        <tbody>
          {failures.map((failure) => (
            <tr
              key={failure.id}
              className="border-b border-slate-100 dark:border-slate-800 last:border-0"
            >
              <td className="py-3 text-xs text-slate-600 dark:text-slate-400 font-mono">
                {new Date(failure.timestamp).toLocaleString()}
              </td>
              <td className="py-3">
                <span className="px-2 py-0.5 rounded text-[10px] font-medium bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400">
                  {failure.error_type}
                </span>
              </td>
              <td className="py-3 text-xs text-slate-700 dark:text-slate-300">
                {failure.message}
              </td>
              <td className="py-3 text-xs text-slate-500 font-mono">
                {failure.model}
              </td>
              <td className="py-3 text-right">
                <a
                  href={`/sessions?error=${failure.id}`}
                  className="inline-flex items-center gap-1 text-xs text-blue-600 hover:underline"
                >
                  View Trace
                  <ExternalLink className="h-3 w-3" />
                </a>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
