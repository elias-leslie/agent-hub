export function TokenBudgetSlider({
  budget,
  onChange,
}: {
  budget: number;
  onChange: (value: number) => void;
}) {
  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
          Token Budget
        </label>
        <span className="text-sm font-mono text-slate-600 dark:text-slate-400">
          {budget.toLocaleString()} tokens
        </span>
      </div>
      <input
        type="range"
        min={100}
        max={10000}
        step={100}
        value={budget}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
      />
      <div className="flex justify-between text-xs text-slate-500">
        <span>100</span>
        <span>10,000</span>
      </div>
    </div>
  );
}
