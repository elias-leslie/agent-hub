"use client";

import { useProviderStatus } from "@/hooks/use-provider-status";
import { useEffect, useState } from "react";

interface DegradedModeBannerProps {
  /** Position in queue if request is queued */
  queuePosition?: number | null;
  /** Estimated wait time in milliseconds */
  estimatedWaitMs?: number | null;
  /** Callback when banner is dismissed manually */
  onDismiss?: () => void;
}

/**
 * Banner component that shows when providers are degraded or down.
 *
 * Features:
 * - Shows "Limited functionality" when providers degraded
 * - Displays queue position if request is queued
 * - Shows estimated recovery time if available
 * - Auto-dismisses when providers recover
 */
export function DegradedModeBanner({
  queuePosition,
  estimatedWaitMs,
  onDismiss,
}: DegradedModeBannerProps) {
  const { isDegraded, unavailableProviders, recoveryEta, status } =
    useProviderStatus(10000); // Poll every 10s during degraded mode

  const [dismissed, setDismissed] = useState(false);
  const [wasEverDegraded, setWasEverDegraded] = useState(false);

  // Track if we were ever degraded to show recovery message
  useEffect(() => {
    if (isDegraded) {
      setWasEverDegraded(true);
      setDismissed(false);
    }
  }, [isDegraded]);

  // Auto-dismiss when recovered
  useEffect(() => {
    if (wasEverDegraded && !isDegraded) {
      // Show "recovered" message briefly before dismissing
      const timeout = setTimeout(() => {
        setWasEverDegraded(false);
      }, 3000);
      return () => clearTimeout(timeout);
    }
  }, [isDegraded, wasEverDegraded]);

  const handleDismiss = () => {
    setDismissed(true);
    onDismiss?.();
  };

  // Don't show if dismissed or not degraded (and wasn't recently degraded)
  if (dismissed || (!isDegraded && !wasEverDegraded)) {
    return null;
  }

  // Show recovery message
  if (!isDegraded && wasEverDegraded) {
    return (
      <div className="bg-green-50 dark:bg-green-900/20 border-b border-green-200 dark:border-green-800 px-4 py-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-green-500" />
            <span className="text-sm text-green-600 dark:text-green-400">
              All providers recovered. Full functionality restored.
            </span>
          </div>
        </div>
      </div>
    );
  }

  const formatTime = (ms: number): string => {
    const seconds = Math.ceil(ms / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.ceil(seconds / 60);
    return `${minutes}m`;
  };

  return (
    <div className="bg-yellow-50 dark:bg-yellow-900/20 border-b border-yellow-200 dark:border-yellow-800 px-4 py-2">
      <div className="flex items-center justify-between">
        <div className="flex flex-col gap-1">
          {/* Main message */}
          <div className="flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-yellow-500 animate-pulse" />
            <span className="text-sm font-medium text-yellow-700 dark:text-yellow-400">
              Limited functionality
            </span>
            {unavailableProviders.length > 0 && (
              <span className="text-sm text-yellow-600 dark:text-yellow-500">
                ({unavailableProviders.join(", ")} unavailable)
              </span>
            )}
          </div>

          {/* Queue info */}
          {queuePosition !== null && queuePosition !== undefined && (
            <div className="text-sm text-yellow-600 dark:text-yellow-500 ml-4">
              Your request is queued (position: {queuePosition})
              {estimatedWaitMs && estimatedWaitMs > 0 && (
                <span> - estimated wait: {formatTime(estimatedWaitMs)}</span>
              )}
            </div>
          )}

          {/* Recovery ETA */}
          {recoveryEta && recoveryEta > 0 && (
            <div className="text-sm text-yellow-600 dark:text-yellow-500 ml-4">
              Estimated recovery: {formatTime(recoveryEta)}
            </div>
          )}
        </div>

        {/* Dismiss button */}
        <button
          onClick={handleDismiss}
          className="text-yellow-600 dark:text-yellow-400 hover:text-yellow-800 dark:hover:text-yellow-200 p-1"
          aria-label="Dismiss banner"
        >
          <svg
            xmlns="http://www.w3.org/2000/svg"
            className="h-4 w-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={2}
              d="M6 18L18 6M6 6l12 12"
            />
          </svg>
        </button>
      </div>
    </div>
  );
}
