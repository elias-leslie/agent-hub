export function StatItem({ label, value, unit }: { label: string; value: string | number; unit?: string }) {
  return (
    <div className="flex justify-between items-center py-1">
      <span className="text-xs text-slate-500">{label}</span>
      <span className="text-xs font-mono font-semibold text-slate-700 dark:text-slate-300">
        {value}
        {unit && <span className="text-slate-400 ml-0.5">{unit}</span>}
      </span>
    </div>
  );
}
