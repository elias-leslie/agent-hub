import type { LucideIcon } from "lucide-react";

interface TierLimitSliderProps {
  label: string;
  icon: LucideIcon;
  value: number;
  max: number;
  onChange: (value: number) => void;
  colorClass: string;
  borderColorClass: string;
  bgColorClass: string;
  accentColorClass: string;
}

export function TierLimitSlider({
  label,
  icon: Icon,
  value,
  max,
  onChange,
  colorClass,
  borderColorClass,
  bgColorClass,
  accentColorClass,
}: TierLimitSliderProps) {
  return (
    <div className={`p-3 rounded-lg border ${borderColorClass} ${bgColorClass}`}>
      <div className="flex items-center gap-2 mb-2">
        <Icon className={`w-4 h-4 ${colorClass}`} />
        <span className={`text-sm font-medium ${colorClass}`}>{label}</span>
        <span className={`ml-auto text-sm font-mono ${colorClass}`}>
          {value === 0 ? "∞" : value}
        </span>
      </div>
      <input
        type="range"
        min={0}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(parseInt(e.target.value))}
        className={`w-full h-2 rounded-lg appearance-none cursor-pointer ${accentColorClass}`}
      />
      <div className={`flex justify-between text-xs mt-1 opacity-70 ${colorClass}`}>
        <span>∞</span>
        <span>{max}</span>
      </div>
    </div>
  );
}
