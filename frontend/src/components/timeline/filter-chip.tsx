import { cn } from "@/lib/utils";
import type { SessionTimelineEvent } from "@/lib/api";
import { getEventConfig } from "./event-config";

type EventType = SessionTimelineEvent["event_type"];

interface FilterChipProps {
  label: string;
  eventType: EventType;
  isActive: boolean;
  count: number;
  onClick: () => void;
}

export function FilterChip({ label, eventType, isActive, count, onClick }: FilterChipProps) {
  const config = getEventConfig(eventType);
  const Icon = config.icon;

  return (
    <button
      onClick={onClick}
      className={cn(
        "flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg",
        "text-xs font-medium tracking-wide",
        "border transition-all duration-200",
        isActive
          ? cn(config.bgColor, config.borderColor, config.color)
          : "bg-slate-900/40 border-slate-800/50 text-slate-500 hover:text-slate-400 hover:border-slate-700"
      )}
    >
      <Icon className="w-3.5 h-3.5" />
      <span>{label}</span>
      <span
        className={cn(
          "px-1.5 py-0.5 rounded text-[10px] font-mono",
          isActive ? "bg-slate-400/10" : "bg-slate-800/60"
        )}
      >
        {count}
      </span>
    </button>
  );
}
