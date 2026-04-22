import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type PersonaDataSource = "runtime" | "session" | "preview" | "advisory" | "draft";

const SOURCE_STYLES: Record<PersonaDataSource, string> = {
  runtime: "border-emerald-500/30 bg-emerald-950/30 text-emerald-200",
  session: "border-slate-700 bg-slate-950/80 text-slate-300",
  preview: "border-violet-500/30 bg-violet-950/30 text-violet-200",
  advisory: "border-sky-500/30 bg-sky-950/30 text-sky-200",
  draft: "border-amber-500/30 border-dashed bg-amber-950/25 text-amber-200",
};

const SOURCE_LABELS: Record<PersonaDataSource, string> = {
  runtime: "Runtime",
  session: "Session",
  preview: "Preview",
  advisory: "Advisory",
  draft: "Draft",
};

export function ProvenanceBadge({
  source,
  className,
}: {
  source: PersonaDataSource;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2 py-0.5 font-mono text-[10px] font-semibold uppercase tracking-[0.18em]",
        SOURCE_STYLES[source],
        className,
      )}
    >
      {SOURCE_LABELS[source]}
    </span>
  );
}

export function SectionEyebrow({
  icon,
  label,
  source,
  className,
}: {
  icon?: ReactNode;
  label: string;
  source?: PersonaDataSource;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-500", className)}>
      {icon ? <span className="text-slate-400">{icon}</span> : null}
      <span>{label}</span>
      {source ? <ProvenanceBadge source={source} /> : null}
    </div>
  );
}

export function ScopeChip({
  children,
  tone = "default",
  className,
}: {
  children: ReactNode;
  tone?: "default" | "warning" | "danger";
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium",
        tone === "warning"
          ? "border-amber-500/30 bg-amber-950/25 text-amber-200"
          : tone === "danger"
            ? "border-rose-500/30 bg-rose-950/25 text-rose-200"
            : "border-slate-700 bg-slate-950/80 text-slate-300",
        className,
      )}
    >
      {children}
    </span>
  );
}
