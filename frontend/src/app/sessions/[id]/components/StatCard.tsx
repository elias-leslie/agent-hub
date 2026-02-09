import { cn } from "@/lib/utils";
import { Activity } from "lucide-react";

interface StatCardProps {
  icon: typeof Activity;
  label: string;
  value: string | number;
  subValue?: string;
}

export function StatCard({ icon: Icon, label, value, subValue }: StatCardProps) {
  return (
    <div
      className={cn(
        "p-3 rounded-lg",
        "bg-slate-900/60 border border-slate-800/60"
      )}
    >
      <div className="flex items-center gap-2 mb-1">
        <Icon className="h-3.5 w-3.5 text-slate-500" />
        <span className="text-xs text-slate-500">{label}</span>
      </div>
      <p className="text-sm font-medium text-slate-300 truncate">{value}</p>
      {subValue && (
        <p className="text-xs text-slate-600 mt-0.5 truncate">{subValue}</p>
      )}
    </div>
  );
}
