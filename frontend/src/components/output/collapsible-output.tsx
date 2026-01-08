"use client";

import { useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { cn } from "@/lib/utils";

interface CollapsibleOutputProps {
  children: React.ReactNode;
  maxHeight?: number;
  className?: string;
  label?: string;
}

export function CollapsibleOutput({
  children,
  maxHeight = 300,
  className,
  label,
}: CollapsibleOutputProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const [needsCollapse, setNeedsCollapse] = useState(false);
  const contentRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (contentRef.current) {
      const contentHeight = contentRef.current.scrollHeight;
      setNeedsCollapse(contentHeight > maxHeight);
    }
  }, [children, maxHeight]);

  if (!needsCollapse) {
    return <div className={className}>{children}</div>;
  }

  return (
    <div className={cn("relative", className)}>
      {/* Content container */}
      <div
        ref={contentRef}
        className={cn("overflow-hidden transition-all duration-300 ease-out")}
        style={{
          maxHeight: isExpanded ? contentRef.current?.scrollHeight : maxHeight,
        }}
      >
        {children}
      </div>

      {/* Gradient fade overlay when collapsed */}
      {!isExpanded && (
        <div
          className={cn(
            "absolute bottom-0 left-0 right-0 h-20 pointer-events-none",
            "bg-gradient-to-t from-white dark:from-[oklch(0.145_0_0)] to-transparent"
          )}
        />
      )}

      {/* Toggle button */}
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className={cn(
          "relative w-full mt-2 py-2 px-4 rounded-md",
          "flex items-center justify-center gap-2",
          "text-sm font-medium tracking-wide",
          "bg-[oklch(0.96_0_0)] dark:bg-[oklch(0.18_0_0)]",
          "border border-[oklch(0.9_0_0)] dark:border-[oklch(0.25_0_0)]",
          "text-[oklch(0.45_0_0)] dark:text-[oklch(0.65_0_0)]",
          "hover:bg-[oklch(0.93_0_0)] dark:hover:bg-[oklch(0.22_0_0)]",
          "hover:text-[oklch(0.3_0_0)] dark:hover:text-[oklch(0.8_0_0)]",
          "hover:border-[oklch(0.85_0_0)] dark:hover:border-[oklch(0.3_0_0)]",
          "transition-all duration-200",
          "focus:outline-none focus:ring-2 focus:ring-[oklch(0.6_0.1_250)] focus:ring-offset-2",
          "dark:focus:ring-offset-[oklch(0.145_0_0)]"
        )}
      >
        {isExpanded ? (
          <>
            <ChevronUp className="w-4 h-4" />
            <span>Show less</span>
          </>
        ) : (
          <>
            <ChevronDown className="w-4 h-4" />
            <span>{label || "Show more"}</span>
          </>
        )}
      </button>
    </div>
  );
}

// Auto-collapsing text output
interface CollapsibleTextProps {
  text: string;
  maxLines?: number;
  className?: string;
}

export function CollapsibleText({ text, maxLines = 10, className }: CollapsibleTextProps) {
  const [isExpanded, setIsExpanded] = useState(false);
  const lines = text.split("\n");
  const needsCollapse = lines.length > maxLines;

  if (!needsCollapse) {
    return (
      <pre className={cn("whitespace-pre-wrap font-mono text-sm", className)}>{text}</pre>
    );
  }

  const displayedLines = isExpanded ? lines : lines.slice(0, maxLines);
  const hiddenCount = lines.length - maxLines;

  return (
    <div className={className}>
      <pre className="whitespace-pre-wrap font-mono text-sm">{displayedLines.join("\n")}</pre>

      {!isExpanded && (
        <div
          className={cn(
            "mt-1 pt-2 border-t border-dashed",
            "border-[oklch(0.85_0_0)] dark:border-[oklch(0.3_0_0)]"
          )}
        >
          <button
            onClick={() => setIsExpanded(true)}
            className={cn(
              "text-sm font-medium",
              "text-[oklch(0.5_0.1_250)] dark:text-[oklch(0.65_0.1_250)]",
              "hover:text-[oklch(0.4_0.15_250)] dark:hover:text-[oklch(0.75_0.15_250)]",
              "transition-colors"
            )}
          >
            + {hiddenCount} more line{hiddenCount > 1 ? "s" : ""}
          </button>
        </div>
      )}

      {isExpanded && (
        <button
          onClick={() => setIsExpanded(false)}
          className={cn(
            "mt-2 text-sm font-medium",
            "text-[oklch(0.5_0.1_250)] dark:text-[oklch(0.65_0.1_250)]",
            "hover:text-[oklch(0.4_0.15_250)] dark:hover:text-[oklch(0.75_0.15_250)]",
            "transition-colors"
          )}
        >
          Show less
        </button>
      )}
    </div>
  );
}
