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

function pillClassName(isClaude: boolean, isActive: boolean, clickable: boolean) {
  return cn(
    "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-all",
    clickable &&
      "cursor-pointer hover:border-slate-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/50",
    isActive && "ring-2 ring-offset-1 ring-offset-slate-950",
    isClaude
      ? cn(
          "border-purple-400/40 bg-purple-950/40 text-purple-300",
          isActive && "ring-purple-400/60",
        )
      : cn(
          "border-emerald-400/40 bg-emerald-950/40 text-emerald-300",
          isActive && "ring-emerald-400/60",
        ),
  );
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
  const className = pillClassName(isClaude, Boolean(isActive), Boolean(onClick));
  const content = (
    <>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          isClaude ? "bg-purple-400" : "bg-emerald-400",
        )}
      />
      <span className="max-w-[18ch] truncate sm:max-w-[24ch]">{label}</span>
    </>
  );

  if (onClick) {
    return (
      <button
        type="button"
        aria-label={`Filter model ${model}`}
        onClick={onClick}
        className={className}
        title={`${model} · click to filter`}
      >
        {content}
      </button>
    );
  }

  return (
    <span className={className} title={model}>
      {content}
    </span>
  );
}
