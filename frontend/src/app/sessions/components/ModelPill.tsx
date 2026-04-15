import { cn } from "@/lib/utils";

function formatModelLabel(model: string): string {
  return model
    .replace(/^codex\/(gpt-[0-9.]+)-codex-spark$/i, "codex/$1-spark")
    .replace(/^codex\/(gpt-[0-9.]+)-codex$/i, "codex/$1")
    .replace(/^claude-/, "claude/")
    .replace(/^gemini-/, "gemini/")
    .replace(/-preview(?:-[a-z0-9-]+)?/gi, "")
    .replace(/-latest\b/gi, "")
    .replace(/-exp(?:-[a-z0-9-]+)?/gi, "")
    .replace(/-\d{4}(?:-\d{2}){1,2}\b/g, "")
    .replace(/-(\d)-(\d)\b/g, "-$1.$2")
    .replace(/-image\b/gi, "")
    .replace(/--+/g, "-")
    .replace(/\/+/g, "/")
    .replace(/[-/]\s*$/g, "");
}

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
  const label = formatModelLabel(model);

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
        isActive && "ring-2 ring-offset-1 ring-offset-slate-900",
        isClaude
          ? cn(
              "border-purple-400/60 text-purple-400 bg-purple-950/40",
              isActive && "ring-purple-400"
            )
          : cn(
              "border-emerald-400/60 text-emerald-400 bg-emerald-950/40",
              isActive && "ring-emerald-400"
            )
      )}
      title={onClick ? `${model} · click to filter` : model}
    >
      <span
        className={cn(
          "w-1.5 h-1.5 rounded-full",
          isClaude ? "bg-purple-500" : "bg-emerald-500"
        )}
      />
      <span className="max-w-[20ch] truncate sm:max-w-[24ch]">
        {label}
      </span>
    </span>
  );
}
