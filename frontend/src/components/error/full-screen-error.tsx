"use client";

import { AlertOctagon, RefreshCw, Mail, Home, ChevronDown } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/utils";
import type { AppError } from "./types";

interface FullScreenErrorProps {
  error: AppError;
  onRetry?: () => void;
  onGoHome?: () => void;
  onContactSupport?: () => void;
  showTechnicalDetails?: boolean;
}

/**
 * FullScreenError - Critical failure state with recovery options.
 *
 * Design: Calm but serious. Not alarming red - uses deep burgundy/slate.
 * Clear messaging with actionable next steps.
 */
export function FullScreenError({
  error,
  onRetry,
  onGoHome,
  onContactSupport,
  showTechnicalDetails = false,
}: FullScreenErrorProps) {
  const [showDetails, setShowDetails] = useState(showTechnicalDetails);

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-gradient-to-br from-slate-50 via-rose-50/30 to-slate-100 dark:from-slate-950 dark:via-rose-950/10 dark:to-slate-900">
      {/* Subtle background pattern */}
      <div
        className="absolute inset-0 opacity-[0.015] dark:opacity-[0.03]"
        style={{
          backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23000000' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
        }}
      />

      <div className="relative max-w-lg w-full">
        {/* Error card */}
        <div className="bg-white dark:bg-slate-900 rounded-2xl shadow-xl border border-slate-200 dark:border-slate-800 overflow-hidden">
          {/* Header accent */}
          <div className="h-1.5 bg-gradient-to-r from-rose-400 via-rose-500 to-pink-500" />

          <div className="p-8">
            {/* Icon */}
            <div className="flex justify-center mb-6">
              <div className="p-4 rounded-2xl bg-rose-100 dark:bg-rose-900/30">
                <AlertOctagon className="h-12 w-12 text-rose-500 dark:text-rose-400" />
              </div>
            </div>

            {/* Title */}
            <h1 className="text-2xl font-bold text-center text-slate-900 dark:text-slate-100 mb-2">
              {error.title}
            </h1>

            {/* Message */}
            <p className="text-center text-slate-600 dark:text-slate-400 mb-8">
              {error.message}
            </p>

            {/* Actions */}
            <div className="flex flex-col sm:flex-row gap-3 mb-6">
              {onRetry && error.retryable && (
                <button
                  onClick={onRetry}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl",
                    "bg-rose-600 text-white font-medium",
                    "hover:bg-rose-700 transition-colors",
                    "focus:outline-none focus:ring-2 focus:ring-rose-500 focus:ring-offset-2"
                  )}
                >
                  <RefreshCw className="h-5 w-5" />
                  Try Again
                </button>
              )}

              {onGoHome && (
                <button
                  onClick={onGoHome}
                  className={cn(
                    "flex-1 flex items-center justify-center gap-2 px-4 py-3 rounded-xl",
                    "bg-slate-100 text-slate-700 font-medium dark:bg-slate-800 dark:text-slate-300",
                    "hover:bg-slate-200 dark:hover:bg-slate-700 transition-colors",
                    "focus:outline-none focus:ring-2 focus:ring-slate-400 focus:ring-offset-2"
                  )}
                >
                  <Home className="h-5 w-5" />
                  Go Home
                </button>
              )}
            </div>

            {/* Contact support */}
            {onContactSupport && (
              <button
                onClick={onContactSupport}
                className="w-full flex items-center justify-center gap-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                <Mail className="h-4 w-4" />
                Contact Support
              </button>
            )}
          </div>

          {/* Technical details */}
          {error.details && (
            <div className="border-t border-slate-200 dark:border-slate-800">
              <button
                onClick={() => setShowDetails(!showDetails)}
                className="w-full flex items-center justify-between px-6 py-3 text-sm text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
              >
                <span>Technical Details</span>
                <ChevronDown
                  className={cn(
                    "h-4 w-4 transition-transform",
                    showDetails && "rotate-180"
                  )}
                />
              </button>

              {showDetails && (
                <div className="px-6 pb-4">
                  <div className="p-4 rounded-lg bg-slate-100 dark:bg-slate-800 font-mono text-xs text-slate-600 dark:text-slate-400 overflow-x-auto">
                    <p className="mb-2">
                      <span className="text-slate-400 dark:text-slate-500">Error ID:</span>{" "}
                      {error.id}
                    </p>
                    <p className="mb-2">
                      <span className="text-slate-400 dark:text-slate-500">Type:</span>{" "}
                      {error.type}
                    </p>
                    <p className="mb-2">
                      <span className="text-slate-400 dark:text-slate-500">Time:</span>{" "}
                      {error.timestamp.toISOString()}
                    </p>
                    {error.details && (
                      <pre className="mt-3 pt-3 border-t border-slate-200 dark:border-slate-700 whitespace-pre-wrap">
                        {error.details}
                      </pre>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Footer tip */}
        <p className="mt-6 text-center text-sm text-slate-400 dark:text-slate-500">
          If this problem persists, try clearing your browser cache or using a different browser.
        </p>
      </div>
    </div>
  );
}

interface ConnectionLostOverlayProps {
  onRetry: () => void;
  isRetrying?: boolean;
}

/**
 * ConnectionLostOverlay - Overlay for connection issues with auto-retry.
 */
export function ConnectionLostOverlay({
  onRetry,
  isRetrying = false,
}: ConnectionLostOverlayProps) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/80 backdrop-blur-sm">
      <div className="bg-white dark:bg-slate-800 rounded-2xl shadow-2xl p-8 max-w-sm w-full mx-4 text-center">
        <div className="mb-4">
          <div className="inline-flex p-3 rounded-full bg-amber-100 dark:bg-amber-900/30">
            <RefreshCw
              className={cn(
                "h-8 w-8 text-amber-600 dark:text-amber-400",
                isRetrying && "animate-spin"
              )}
            />
          </div>
        </div>

        <h2 className="text-xl font-bold text-slate-900 dark:text-slate-100 mb-2">
          Connection Lost
        </h2>
        <p className="text-slate-600 dark:text-slate-400 mb-6">
          {isRetrying
            ? "Attempting to reconnect..."
            : "We're having trouble connecting. Check your internet connection."}
        </p>

        <button
          onClick={onRetry}
          disabled={isRetrying}
          className={cn(
            "w-full py-3 px-4 rounded-xl font-medium transition-colors",
            "focus:outline-none focus:ring-2 focus:ring-amber-500 focus:ring-offset-2",
            isRetrying
              ? "bg-amber-100 text-amber-600 dark:bg-amber-900/30 dark:text-amber-400"
              : "bg-amber-500 text-white hover:bg-amber-600"
          )}
        >
          {isRetrying ? "Reconnecting..." : "Try Again"}
        </button>
      </div>
    </div>
  );
}
