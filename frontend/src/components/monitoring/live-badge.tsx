"use client";

import { cn } from "@/lib/utils";

interface LiveBadgeProps {
  /** Badge size variant */
  size?: "sm" | "md" | "lg";
  /** Show "Live" text label */
  showLabel?: boolean;
  /** Additional CSS classes */
  className?: string;
}

/**
 * LiveBadge - Animated indicator for active/live sessions.
 *
 * Green pulsing dot with optional "Live" text label.
 * Used on session cards and monitoring panels to indicate active state.
 */
export function LiveBadge({
  size = "md",
  showLabel = true,
  className,
}: LiveBadgeProps) {
  const sizeClasses = {
    sm: "h-1.5 w-1.5",
    md: "h-2 w-2",
    lg: "h-2.5 w-2.5",
  };

  const textSizes = {
    sm: "text-[10px]",
    md: "text-xs",
    lg: "text-sm",
  };

  return (
    <div
      className={cn(
        "inline-flex items-center gap-1.5 font-medium",
        textSizes[size],
        className,
      )}
    >
      <span className="relative flex">
        {/* Pulsing ring */}
        <span
          className={cn(
            "absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-75",
            sizeClasses[size],
          )}
        />
        {/* Solid dot */}
        <span
          className={cn(
            "relative inline-flex rounded-full bg-green-500",
            sizeClasses[size],
          )}
        />
      </span>
      {showLabel && (
        <span className="text-green-600 dark:text-green-400 uppercase tracking-wide font-semibold">
          Live
        </span>
      )}
    </div>
  );
}
