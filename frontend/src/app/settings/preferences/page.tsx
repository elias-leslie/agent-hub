"use client";

import { useState, useEffect, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Settings,
  Sliders,
  MessageSquare,
  Cpu,
  Save,
  RotateCcw,
  Check,
  Gauge,
  Volume2,
  Bot,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  fetchUserPreferences,
  updateUserPreferences,
  type UserPreferences,
} from "@/lib/api";

const VERBOSITY_LEVELS = [
  { id: "concise", label: "Concise", description: "Brief, to-the-point responses" },
  { id: "normal", label: "Normal", description: "Balanced detail level" },
  { id: "detailed", label: "Detailed", description: "Thorough explanations" },
] as const;

const TONE_OPTIONS = [
  { id: "professional", label: "Professional", icon: "◼", description: "Formal and business-like" },
  { id: "friendly", label: "Friendly", icon: "●", description: "Warm and approachable" },
  { id: "technical", label: "Technical", icon: "◆", description: "Precise and detailed" },
] as const;

const MODEL_OPTIONS = [
  { id: "claude-sonnet-4-5", label: "Claude Sonnet 4.5", provider: "claude", tier: "default" },
  { id: "claude-opus-4-5", label: "Claude Opus 4.5", provider: "claude", tier: "premium" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5", provider: "claude", tier: "fast" },
  { id: "gemini-3-flash-preview", label: "Gemini 3 Flash", provider: "gemini", tier: "default" },
  { id: "gemini-3-pro-preview", label: "Gemini 3 Pro", provider: "gemini", tier: "premium" },
] as const;

type VerbosityLevel = (typeof VERBOSITY_LEVELS)[number]["id"];
type ToneOption = (typeof TONE_OPTIONS)[number]["id"];
type ModelOption = (typeof MODEL_OPTIONS)[number]["id"];

const DEFAULT_PREFERENCES: UserPreferences = {
  verbosity: "normal",
  tone: "professional",
  default_model: "claude-sonnet-4-5",
};

export default function PreferencesPage() {
  const queryClient = useQueryClient();
  const [localPrefs, setLocalPrefs] = useState<UserPreferences>(DEFAULT_PREFERENCES);
  const [hasChanges, setHasChanges] = useState(false);
  const [saveStatus, setSaveStatus] = useState<"idle" | "saving" | "saved">("idle");

  // Fetch preferences
  const { data, isLoading } = useQuery({
    queryKey: ["userPreferences"],
    queryFn: fetchUserPreferences,
  });

  // Update local state when data loads
  useEffect(() => {
    if (data) {
      setLocalPrefs(data);
      setHasChanges(false);
    }
  }, [data]);

  // Save mutation
  const saveMutation = useMutation({
    mutationFn: updateUserPreferences,
    onSuccess: (newData) => {
      queryClient.setQueryData(["userPreferences"], newData);
      setHasChanges(false);
      setSaveStatus("saved");
      setTimeout(() => setSaveStatus("idle"), 2000);
    },
  });

  const updatePreference = useCallback(
    <K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) => {
      setLocalPrefs((prev) => ({ ...prev, [key]: value }));
      setHasChanges(true);
      setSaveStatus("idle");
    },
    []
  );

  const handleSave = () => {
    setSaveStatus("saving");
    saveMutation.mutate(localPrefs);
  };

  const handleReset = () => {
    if (data) {
      setLocalPrefs(data);
      setHasChanges(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-slate-950">
      {/* Header with control panel aesthetic */}
      <header className="sticky top-0 z-10 border-b border-slate-200 dark:border-slate-800 bg-white/80 dark:bg-slate-900/80 backdrop-blur-lg">
        <div className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-3">
              <div className="relative p-2 rounded-lg bg-slate-100 dark:bg-slate-800">
                <Sliders className="h-5 w-5 text-slate-600 dark:text-slate-400" />
                {/* Status indicator light */}
                <span
                  className={cn(
                    "absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full",
                    hasChanges
                      ? "bg-amber-400 animate-pulse"
                      : "bg-emerald-400"
                  )}
                />
              </div>
              <div>
                <h1 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
                  Preferences
                </h1>
                <p className="text-xs text-slate-500 dark:text-slate-400 font-mono">
                  SYS.CONFIG.USER
                </p>
              </div>
            </div>

            {/* Save controls */}
            <div className="flex items-center gap-2">
              {hasChanges && (
                <button
                  onClick={handleReset}
                  className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
                >
                  <RotateCcw className="h-4 w-4" />
                  Reset
                </button>
              )}
              <button
                onClick={handleSave}
                disabled={!hasChanges || saveMutation.isPending}
                className={cn(
                  "flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-medium transition-all duration-200",
                  hasChanges
                    ? [
                        "bg-emerald-500 hover:bg-emerald-600 text-white",
                        "shadow-lg shadow-emerald-500/25 hover:shadow-emerald-500/40",
                      ]
                    : saveStatus === "saved"
                    ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-600 dark:text-emerald-400"
                    : "bg-slate-100 dark:bg-slate-800 text-slate-400 cursor-not-allowed"
                )}
              >
                {saveMutation.isPending ? (
                  <>
                    <span className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />
                    Saving...
                  </>
                ) : saveStatus === "saved" ? (
                  <>
                    <Check className="h-4 w-4" />
                    Saved
                  </>
                ) : (
                  <>
                    <Save className="h-4 w-4" />
                    Save
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {isLoading ? (
          <div className="flex items-center justify-center py-20">
            <div className="flex items-center gap-3 text-slate-500">
              <span className="h-5 w-5 border-2 border-slate-300 border-t-slate-600 rounded-full animate-spin" />
              Loading preferences...
            </div>
          </div>
        ) : (
          <div className="space-y-8">
            {/* Verbosity Control - Industrial Slider Style */}
            <section className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center gap-3 mb-6">
                <div className="p-2 rounded-lg bg-amber-100 dark:bg-amber-900/30">
                  <Gauge className="h-5 w-5 text-amber-600 dark:text-amber-400" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                    Response Verbosity
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Control how detailed AI responses should be
                  </p>
                </div>
              </div>

              {/* Industrial switch track */}
              <div className="relative">
                {/* Track background */}
                <div className="flex rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700">
                  {VERBOSITY_LEVELS.map((level, idx) => (
                    <button
                      key={level.id}
                      onClick={() => updatePreference("verbosity", level.id as VerbosityLevel)}
                      className={cn(
                        "flex-1 relative py-4 px-4 transition-all duration-200",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-amber-500",
                        localPrefs.verbosity === level.id
                          ? [
                              "bg-amber-50 dark:bg-amber-950/40",
                              "text-amber-700 dark:text-amber-300",
                            ]
                          : [
                              "bg-slate-50 dark:bg-slate-800/50",
                              "text-slate-500 dark:text-slate-400",
                              "hover:bg-slate-100 dark:hover:bg-slate-800",
                            ],
                        idx > 0 && "border-l border-slate-200 dark:border-slate-700"
                      )}
                    >
                      <div className="flex flex-col items-center gap-1">
                        <span
                          className={cn(
                            "text-sm font-semibold",
                            localPrefs.verbosity === level.id &&
                              "text-amber-600 dark:text-amber-400"
                          )}
                        >
                          {level.label}
                        </span>
                        <span className="text-xs opacity-70">{level.description}</span>
                      </div>
                      {/* Selection indicator */}
                      {localPrefs.verbosity === level.id && (
                        <span className="absolute bottom-0 left-1/2 -translate-x-1/2 w-8 h-1 rounded-t-full bg-amber-500" />
                      )}
                    </button>
                  ))}
                </div>

                {/* Meter bars visualization */}
                <div className="mt-4 flex items-center justify-center gap-1">
                  {[1, 2, 3, 4, 5].map((bar) => {
                    const isActive =
                      (localPrefs.verbosity === "concise" && bar <= 2) ||
                      (localPrefs.verbosity === "normal" && bar <= 3) ||
                      (localPrefs.verbosity === "detailed" && bar <= 5);
                    return (
                      <div
                        key={bar}
                        className={cn(
                          "w-3 rounded-sm transition-all duration-300",
                          isActive
                            ? "bg-amber-400 dark:bg-amber-500"
                            : "bg-slate-200 dark:bg-slate-700"
                        )}
                        style={{ height: `${bar * 6 + 8}px` }}
                      />
                    );
                  })}
                </div>
              </div>
            </section>

            {/* Tone Selection - Toggle Button Group */}
            <section className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center gap-3 mb-6">
                <div className="p-2 rounded-lg bg-blue-100 dark:bg-blue-900/30">
                  <Volume2 className="h-5 w-5 text-blue-600 dark:text-blue-400" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                    Response Tone
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Set the communication style for AI responses
                  </p>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-3">
                {TONE_OPTIONS.map((tone) => (
                  <button
                    key={tone.id}
                    onClick={() => updatePreference("tone", tone.id as ToneOption)}
                    className={cn(
                      "relative flex flex-col items-center gap-2 p-4 rounded-lg border-2 transition-all duration-200",
                      "focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/50",
                      localPrefs.tone === tone.id
                        ? [
                            "border-blue-400 dark:border-blue-500",
                            "bg-blue-50 dark:bg-blue-950/30",
                            "shadow-lg shadow-blue-500/10",
                          ]
                        : [
                            "border-slate-200 dark:border-slate-700",
                            "hover:border-slate-300 dark:hover:border-slate-600",
                            "hover:bg-slate-50 dark:hover:bg-slate-800/50",
                          ]
                    )}
                  >
                    {/* Icon with glow effect when selected */}
                    <div
                      className={cn(
                        "relative flex items-center justify-center w-10 h-10 rounded-full text-lg font-mono",
                        localPrefs.tone === tone.id
                          ? "bg-blue-200 dark:bg-blue-800 text-blue-600 dark:text-blue-300"
                          : "bg-slate-100 dark:bg-slate-800 text-slate-500"
                      )}
                    >
                      {tone.icon}
                      {localPrefs.tone === tone.id && (
                        <span className="absolute inset-0 rounded-full bg-blue-400/30 animate-pulse" />
                      )}
                    </div>
                    <div className="text-center">
                      <p
                        className={cn(
                          "font-semibold text-sm",
                          localPrefs.tone === tone.id
                            ? "text-blue-700 dark:text-blue-300"
                            : "text-slate-700 dark:text-slate-300"
                        )}
                      >
                        {tone.label}
                      </p>
                      <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
                        {tone.description}
                      </p>
                    </div>
                    {/* Selection indicator */}
                    {localPrefs.tone === tone.id && (
                      <span className="absolute top-2 right-2 w-2 h-2 rounded-full bg-blue-500" />
                    )}
                  </button>
                ))}
              </div>
            </section>

            {/* Default Model Selection */}
            <section className="p-6 rounded-xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
              <div className="flex items-center gap-3 mb-6">
                <div className="p-2 rounded-lg bg-violet-100 dark:bg-violet-900/30">
                  <Bot className="h-5 w-5 text-violet-600 dark:text-violet-400" />
                </div>
                <div>
                  <h2 className="text-base font-semibold text-slate-900 dark:text-slate-100">
                    Default Model
                  </h2>
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Choose your preferred AI model for new conversations
                  </p>
                </div>
              </div>

              <div className="space-y-2">
                {MODEL_OPTIONS.map((model) => {
                  const isSelected = localPrefs.default_model === model.id;
                  return (
                    <button
                      key={model.id}
                      onClick={() => updatePreference("default_model", model.id as ModelOption)}
                      className={cn(
                        "w-full flex items-center gap-4 p-3 rounded-lg border transition-all duration-200",
                        "focus:outline-none focus-visible:ring-2 focus-visible:ring-violet-500/50",
                        isSelected
                          ? [
                              "border-violet-400 dark:border-violet-500",
                              "bg-violet-50 dark:bg-violet-950/30",
                            ]
                          : [
                              "border-slate-200 dark:border-slate-700",
                              "hover:border-slate-300 dark:hover:border-slate-600",
                              "hover:bg-slate-50 dark:hover:bg-slate-800/50",
                            ]
                      )}
                    >
                      {/* Radio indicator */}
                      <div
                        className={cn(
                          "relative w-5 h-5 rounded-full border-2 flex items-center justify-center transition-colors",
                          isSelected
                            ? "border-violet-500 bg-violet-500"
                            : "border-slate-300 dark:border-slate-600"
                        )}
                      >
                        {isSelected && (
                          <span className="w-2 h-2 rounded-full bg-white" />
                        )}
                      </div>

                      {/* Provider icon */}
                      <div
                        className={cn(
                          "p-1.5 rounded",
                          model.provider === "claude"
                            ? "bg-orange-100 dark:bg-orange-900/30"
                            : "bg-blue-100 dark:bg-blue-900/30"
                        )}
                      >
                        <Cpu
                          className={cn(
                            "h-4 w-4",
                            model.provider === "claude"
                              ? "text-orange-500"
                              : "text-blue-500"
                          )}
                        />
                      </div>

                      {/* Model info */}
                      <div className="flex-1 text-left">
                        <p
                          className={cn(
                            "font-medium text-sm",
                            isSelected
                              ? "text-violet-700 dark:text-violet-300"
                              : "text-slate-700 dark:text-slate-300"
                          )}
                        >
                          {model.label}
                        </p>
                      </div>

                      {/* Tier badge */}
                      <span
                        className={cn(
                          "px-2 py-0.5 rounded text-xs font-medium",
                          model.tier === "premium"
                            ? "bg-amber-100 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300"
                            : model.tier === "fast"
                            ? "bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300"
                            : "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400"
                        )}
                      >
                        {model.tier}
                      </span>
                    </button>
                  );
                })}
              </div>
            </section>

            {/* Settings link */}
            <div className="flex items-center justify-center gap-4 pt-4 border-t border-slate-200 dark:border-slate-800">
              <a
                href="/settings"
                className="flex items-center gap-2 text-sm text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-300 transition-colors"
              >
                <Settings className="h-4 w-4" />
                Back to Settings
              </a>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}
