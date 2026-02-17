import { cn } from "@/lib/utils";

export function ModelPill({
  model,
  provider,
  onClick,
  isActive,
}: {
  model: string;
  provider?: string;
  onClick?: () => void;
  isActive?: boolean;
}) {
  const isClaude = provider ? provider === "claude" : model.toLowerCase().includes("claude");

  // Extract meaningful model name
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-preview", "")
    .replace("-20250514", "")
    .replace("-image", "")
    .slice(0, 12);

  return (
    <span
      onClick={(e) => {
        if (onClick) {
          e.stopPropagation();
          onClick();
        }
      }}
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border transition-all",
        onClick && "cursor-pointer hover:scale-105 active:scale-95",
        isActive && "ring-2 ring-offset-1 ring-offset-white dark:ring-offset-slate-900",
        isClaude
          ? cn(
              "border-purple-400/60 text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40",
              isActive && "ring-purple-400"
            )
          : cn(
              "border-emerald-400/60 text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40",
              isActive && "ring-emerald-400"
            )
      )}
      title={onClick ? "Click to filter by model" : undefined}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isClaude ? "bg-purple-500" : "bg-emerald-500"
        )}
      />
      {shortName}
    </span>
  );
}
