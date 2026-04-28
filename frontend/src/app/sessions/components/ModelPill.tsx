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

function pillClassName(isActive: boolean, clickable: boolean) {
  return cn(
    "inline-flex items-center gap-1.5 rounded-full border border-slate-800/90 bg-slate-950/40 px-2 py-0.5 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-400 transition-all",
    clickable &&
      "cursor-pointer hover:border-slate-700 hover:bg-slate-950/70 hover:text-slate-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-400/40",
    isActive && "border-amber-500/25 bg-amber-950/12 text-amber-200 ring-1 ring-amber-400/20",
  );
}

export function ModelPill({
  model,
  provider,
  onClick,
  isActive,
  fallbackUsed = false,
}: {
  model: string;
  provider?: string;
  onClick?: () => void;
  isActive?: boolean;
  fallbackUsed?: boolean;
}) {
  const label = formatModelLabel(model);
  const className = pillClassName(Boolean(isActive), Boolean(onClick));
  const content = (
    <>
      <span
        className={cn(
          "h-1.5 w-1.5 rounded-full",
          isActive ? "bg-amber-300" : fallbackUsed ? "bg-amber-400/80" : "bg-slate-600",
        )}
      />
      <span className="max-w-[18ch] truncate sm:max-w-[24ch]">{label}</span>
    </>
  );
  const title = [model, fallbackUsed ? "fallback used" : null, provider].filter(Boolean).join(" · ");

  if (onClick) {
    return (
      <button
        type="button"
        aria-label={`Filter model ${model}`}
        onClick={(event) => {
          event.stopPropagation();
          onClick();
        }}
        className={className}
        title={title}
      >
        {content}
      </button>
    );
  }

  return (
    <span className={className} title={title}>
      {content}
    </span>
  );
}
