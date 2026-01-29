import { cn } from "@/lib/utils";

export function ModelPill({ model }: { model: string }) {
  const isClaude = model.toLowerCase().includes("claude");
  const shortName = model
    .replace("claude-", "")
    .replace("gemini-", "")
    .replace("-20250514", "")
    .slice(0, 12);

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 px-2 py-0.5 rounded text-[10px] font-semibold uppercase tracking-wide border",
        isClaude
          ? "border-purple-400/60 text-purple-600 dark:text-purple-400 bg-purple-50/80 dark:bg-purple-950/40"
          : "border-emerald-400/60 text-emerald-600 dark:text-emerald-400 bg-emerald-50/80 dark:bg-emerald-950/40"
      )}
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
