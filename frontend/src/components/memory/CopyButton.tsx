"use client";

import { useState } from "react";
import { Copy, Check } from "lucide-react";
import { cn } from "@/lib/utils";

export function CopyButton({
  text,
  className,
}: {
  text: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    await navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  return (
    <button
      onClick={handleCopy}
      className={cn(
        "relative p-1 rounded-md transition-all cursor-pointer",
        "hover:bg-slate-200 dark:hover:bg-slate-700",
        "active:scale-95",
        className
      )}
      title={copied ? undefined : "Copy to clipboard"}
    >
      {copied ? (
        <Check className="h-3 w-3 text-emerald-500" />
      ) : (
        <Copy className="h-3 w-3 text-slate-400 hover:text-slate-600 dark:hover:text-slate-300" />
      )}
      {copied && (
        <span className="absolute -top-7 left-1/2 -translate-x-1/2 px-2 py-0.5 text-[10px] font-medium rounded bg-emerald-600 text-white whitespace-nowrap animate-in fade-in-0 zoom-in-95 duration-150">
          Copied!
        </span>
      )}
    </button>
  );
}
