"use client";

import { useState, useEffect } from "react";
import { X, Settings, ToggleLeft, ToggleRight, Gauge, Power } from "lucide-react";
import {
  getSettings,
  updateSettings,
  getBudgetUsage,
  type MemorySettings,
  type BudgetUsage,
} from "@/lib/api/memory-settings";

export function MemorySettingsModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean;
  onClose: () => void;
}) {
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [usage, setUsage] = useState<BudgetUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Editable state
  const [enabled, setEnabled] = useState(true);
  const [budgetEnabled, setBudgetEnabled] = useState(true);
  const [budget, setBudget] = useState(2000);

  useEffect(() => {
    if (isOpen) {
      loadData();
    }
  }, [isOpen]);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [settingsData, usageData] = await Promise.all([
        getSettings(),
        getBudgetUsage(),
      ]);
      setSettings(settingsData);
      setUsage(usageData);
      setEnabled(settingsData.enabled);
      setBudgetEnabled(settingsData.budget_enabled);
      setBudget(settingsData.total_budget);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const updated = await updateSettings({
        enabled,
        budget_enabled: budgetEnabled,
        total_budget: budget,
      });
      setSettings(updated);
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (!isOpen) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="settings-modal"
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-slate-200 dark:border-slate-800">
          <div className="flex items-center gap-3">
            <div className="p-2 rounded-full bg-blue-100 dark:bg-blue-900/30">
              <Settings className="w-5 h-5 text-blue-600 dark:text-blue-400" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900 dark:text-slate-100">
              Memory Settings
            </h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-slate-600 hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Content */}
        <div className="p-4 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="p-3 rounded-lg bg-red-50 dark:bg-red-900/20 text-red-600 dark:text-red-400 text-sm">
              {error}
            </div>
          ) : (
            <>
              {/* Memory Injection Kill Switch */}
              <div className="space-y-2">
                <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                  Memory Injection
                </label>
                <button
                  onClick={() => setEnabled(!enabled)}
                  className={`flex items-center gap-3 w-full p-3 rounded-lg border transition-colors ${
                    enabled
                      ? "border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50"
                      : "border-red-200 dark:border-red-900 bg-red-50 dark:bg-red-900/20"
                  }`}
                >
                  {enabled ? (
                    <Power className="w-6 h-6 text-green-500" />
                  ) : (
                    <Power className="w-6 h-6 text-red-500" />
                  )}
                  <div className="text-left">
                    <div className="font-medium text-slate-900 dark:text-slate-100">
                      {enabled ? "Active" : "Disabled"}
                    </div>
                    <div className="text-xs text-slate-500">
                      {enabled
                        ? "Memories are injected into context"
                        : "No memories will be injected (kill switch)"}
                    </div>
                  </div>
                </button>
              </div>

              {/* Budget Enforcement Toggle - only show when injection is enabled */}
              {enabled && (
                <>
                  <div className="space-y-2">
                    <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                      Budget Enforcement
                    </label>
                    <button
                      onClick={() => setBudgetEnabled(!budgetEnabled)}
                      className="flex items-center gap-3 w-full p-3 rounded-lg border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800/50 transition-colors"
                    >
                      {budgetEnabled ? (
                        <ToggleRight className="w-8 h-8 text-green-500" />
                      ) : (
                        <ToggleLeft className="w-8 h-8 text-amber-500" />
                      )}
                      <div className="text-left">
                        <div className="font-medium text-slate-900 dark:text-slate-100">
                          {budgetEnabled ? "Limited" : "Unlimited"}
                        </div>
                        <div className="text-xs text-slate-500">
                          {budgetEnabled
                            ? `Limit injection to ${budget.toLocaleString()} tokens`
                            : "Inject all memories (no limit)"}
                        </div>
                      </div>
                    </button>
                  </div>

                  {/* Token Budget Slider - only show when budget is enabled */}
                  {budgetEnabled && (
                    <div className="space-y-3">
                      <div className="flex items-center justify-between">
                        <label className="text-sm font-medium text-slate-700 dark:text-slate-300">
                          Token Budget
                        </label>
                        <span className="text-sm font-mono text-slate-600 dark:text-slate-400">
                          {budget.toLocaleString()} tokens
                        </span>
                      </div>
                      <input
                        type="range"
                        min={100}
                        max={10000}
                        step={100}
                        value={budget}
                        onChange={(e) => setBudget(parseInt(e.target.value))}
                        className="w-full h-2 bg-slate-200 dark:bg-slate-700 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                      <div className="flex justify-between text-xs text-slate-500">
                        <span>100</span>
                        <span>10,000</span>
                      </div>
                    </div>
                  )}

                  {/* Budget Usage Display */}
                  {usage && (
                    <div className="space-y-2 p-3 rounded-lg bg-slate-50 dark:bg-slate-800/50">
                      <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                        <Gauge className="w-4 h-4" />
                        Budget Usage
                      </div>
                      <div className="space-y-1.5 text-sm">
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500">Mandates</span>
                          <div className="text-right">
                            <span className="font-mono text-slate-700 dark:text-slate-300">
                              {usage.mandates_injected}/{usage.mandates_total}
                            </span>
                            {usage.mandates_total - usage.mandates_injected > 0 && (
                              <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
                                {usage.mandates_total - usage.mandates_injected} cut
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500">Guardrails</span>
                          <div className="text-right">
                            <span className="font-mono text-slate-700 dark:text-slate-300">
                              {usage.guardrails_injected}/{usage.guardrails_total}
                            </span>
                            {usage.guardrails_total - usage.guardrails_injected > 0 && (
                              <span className="ml-2 text-xs text-amber-600 dark:text-amber-400">
                                {usage.guardrails_total - usage.guardrails_injected} cut
                              </span>
                            )}
                          </div>
                        </div>
                        <div className="flex justify-between items-center">
                          <span className="text-slate-500">Reference</span>
                          <div className="text-right">
                            <span className="font-mono text-slate-700 dark:text-slate-300">
                              {usage.reference_injected}/{usage.reference_total}
                            </span>
                          </div>
                        </div>
                        <div className="pt-1.5 border-t border-slate-200 dark:border-slate-700">
                          <div className="flex justify-between font-medium">
                            <span className="text-slate-700 dark:text-slate-300">
                              Tokens
                            </span>
                            <span
                              className={`font-mono ${
                                usage.hit_limit
                                  ? "text-red-500"
                                  : "text-slate-700 dark:text-slate-300"
                              }`}
                            >
                              {usage.total_tokens.toLocaleString()} / {usage.total_budget.toLocaleString()}
                            </span>
                          </div>
                          <div className="flex justify-between text-xs text-slate-500 mt-1">
                            <span>Coverage</span>
                            <span>
                              {Math.round(
                                ((usage.mandates_injected + usage.guardrails_injected + usage.reference_injected) /
                                  Math.max(usage.mandates_total + usage.guardrails_total + usage.reference_total, 1)) *
                                  100
                              )}% of knowledge base
                            </span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-slate-200 dark:border-slate-800">
          <button
            onClick={onClose}
            disabled={saving}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={loading || saving}
            className="px-4 py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-700 text-white disabled:opacity-50 flex items-center gap-2"
          >
            {saving ? (
              <>
                <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                Saving...
              </>
            ) : (
              "Save Changes"
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
