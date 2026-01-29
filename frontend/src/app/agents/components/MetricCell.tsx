import { Sparkline } from "./Sparkline";

/**
 * Metrics cell displaying value + sparkline
 */
export function MetricCell({
  label,
  value,
  unit,
  trend,
  color = "emerald",
}: {
  label: string;
  value: string | number;
  unit?: string;
  trend?: number[];
  color?: "emerald" | "blue" | "amber" | "red";
}) {
  return (
    <div className="flex items-center gap-2">
      <div className="min-w-[50px]">
        <span className="text-xs font-semibold tabular-nums text-slate-700 dark:text-slate-300">
          {value}
        </span>
        {unit && (
          <span className="text-[10px] text-slate-400 ml-0.5">{unit}</span>
        )}
      </div>
      {trend && trend.length > 0 && <Sparkline data={trend} color={color} />}
    </div>
  );
}
