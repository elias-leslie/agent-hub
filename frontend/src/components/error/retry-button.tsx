"use client";

import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { cn } from "@/lib/utils";

interface RetryButtonProps {
  onClick: () => void | Promise<void>;
  label?: string;
  variant?: "warning" | "error" | "neutral";
  size?: "sm" | "md" | "lg";
  disabled?: boolean;
  className?: string;
}

/**
 * RetryButton - Retry action with loading state and animation.
 *
 * Design: Smooth spin animation while retrying, disabled state during load.
 */
export function RetryButton({
  onClick,
  label = "Retry",
  variant = "neutral",
  size = "md",
  disabled = false,
  className,
}: RetryButtonProps) {
  const [isLoading, setIsLoading] = useState(false);

  const handleClick = async () => {
    if (isLoading || disabled) return;

    setIsLoading(true);
    try {
      await onClick();
    } finally {
      // Small delay to show completion
      setTimeout(() => setIsLoading(false), 300);
    }
  };

  const sizeClasses = {
    sm: "px-2 py-1 text-xs gap-1",
    md: "px-3 py-1.5 text-sm gap-1.5",
    lg: "px-4 py-2 text-base gap-2",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  const variantClasses = {
    warning: cn(
      "bg-amber-600 text-white hover:bg-amber-700",
      "dark:bg-amber-500 dark:hover:bg-amber-600",
      "focus:ring-amber-500"
    ),
    error: cn(
      "bg-rose-600 text-white hover:bg-rose-700",
      "dark:bg-rose-500 dark:hover:bg-rose-600",
      "focus:ring-rose-500"
    ),
    neutral: cn(
      "bg-slate-600 text-white hover:bg-slate-700",
      "dark:bg-slate-500 dark:hover:bg-slate-600",
      "focus:ring-slate-500"
    ),
  };

  return (
    <button
      onClick={handleClick}
      disabled={isLoading || disabled}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium",
        "transition-all duration-200",
        "focus:outline-none focus:ring-2 focus:ring-offset-2",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
    >
      <RefreshCw
        className={cn(
          iconSizes[size],
          isLoading && "animate-spin"
        )}
      />
      <span>{isLoading ? "Retrying..." : label}</span>
    </button>
  );
}

interface RetryCountdownButtonProps extends Omit<RetryButtonProps, "onClick"> {
  onClick: () => void | Promise<void>;
  countdownSeconds?: number;
  autoRetry?: boolean;
}

/**
 * RetryCountdownButton - Retry with countdown timer for rate limits.
 */
export function RetryCountdownButton({
  onClick,
  countdownSeconds = 30,
  autoRetry = false,
  label = "Retry",
  variant = "warning",
  size = "md",
  disabled = false,
  className,
}: RetryCountdownButtonProps) {
  const [countdown, setCountdown] = useState(countdownSeconds);
  const [isCountingDown, setIsCountingDown] = useState(true);
  const [isLoading, setIsLoading] = useState(false);

  // Countdown effect
  useState(() => {
    if (!isCountingDown) return;

    const timer = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          clearInterval(timer);
          setIsCountingDown(false);
          if (autoRetry) {
            handleRetry();
          }
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  });

  const handleRetry = async () => {
    if (isLoading || disabled) return;

    setIsLoading(true);
    try {
      await onClick();
    } finally {
      setTimeout(() => setIsLoading(false), 300);
    }
  };

  const sizeClasses = {
    sm: "px-2 py-1 text-xs gap-1",
    md: "px-3 py-1.5 text-sm gap-1.5",
    lg: "px-4 py-2 text-base gap-2",
  };

  const iconSizes = {
    sm: "h-3 w-3",
    md: "h-4 w-4",
    lg: "h-5 w-5",
  };

  const variantClasses = {
    warning: cn(
      isCountingDown
        ? "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300"
        : "bg-amber-600 text-white hover:bg-amber-700 dark:bg-amber-500 dark:hover:bg-amber-600",
      "focus:ring-amber-500"
    ),
    error: cn(
      isCountingDown
        ? "bg-rose-100 text-rose-700 dark:bg-rose-900/50 dark:text-rose-300"
        : "bg-rose-600 text-white hover:bg-rose-700 dark:bg-rose-500 dark:hover:bg-rose-600",
      "focus:ring-rose-500"
    ),
    neutral: cn(
      isCountingDown
        ? "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300"
        : "bg-slate-600 text-white hover:bg-slate-700 dark:bg-slate-500 dark:hover:bg-slate-600",
      "focus:ring-slate-500"
    ),
  };

  return (
    <button
      onClick={handleRetry}
      disabled={isCountingDown || isLoading || disabled}
      className={cn(
        "inline-flex items-center justify-center rounded-lg font-medium",
        "transition-all duration-200",
        "focus:outline-none focus:ring-2 focus:ring-offset-2",
        "disabled:cursor-not-allowed",
        !isCountingDown && "disabled:opacity-50",
        sizeClasses[size],
        variantClasses[variant],
        className
      )}
    >
      <RefreshCw
        className={cn(
          iconSizes[size],
          isLoading && "animate-spin"
        )}
      />
      <span>
        {isLoading
          ? "Retrying..."
          : isCountingDown
            ? `${label} in ${countdown}s`
            : label}
      </span>
    </button>
  );
}
