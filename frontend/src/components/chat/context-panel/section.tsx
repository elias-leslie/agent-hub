import { ChevronDown, ChevronUp } from "lucide-react";

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  badge?: number;
  isExpanded: boolean;
  onToggle: () => void;
  children: React.ReactNode;
  testId?: string;
}

export function Section({
  title,
  icon,
  badge,
  isExpanded,
  onToggle,
  children,
  testId,
}: SectionProps) {
  return (
    <div className="border-b border-slate-200 dark:border-slate-800">
      <button
        data-testid={testId}
        onClick={onToggle}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-50 dark:hover:bg-slate-800/50"
      >
        <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          {icon}
          <span>{title}</span>
          {badge !== undefined && badge > 0 && (
            <span className="px-1.5 py-0.5 rounded-full text-xs bg-slate-200 dark:bg-slate-700 text-slate-600 dark:text-slate-400">
              {badge}
            </span>
          )}
        </div>
        {isExpanded ? (
          <ChevronUp className="h-4 w-4 text-slate-400" />
        ) : (
          <ChevronDown className="h-4 w-4 text-slate-400" />
        )}
      </button>
      {isExpanded && <div className="px-4 pb-4">{children}</div>}
    </div>
  );
}
