"use client";

import { ToggleLeft, ToggleRight, Gauge, Power, Shield, AlertTriangle } from "lucide-react";
import { ModalHeader } from "./ModalHeader";
import { ModalFooter } from "./ModalFooter";
import { ToggleSetting } from "./ToggleSetting";
import { TokenBudgetSlider } from "./TokenBudgetSlider";
import { TierLimitSlider } from "./TierLimitSlider";
import { LLMConfigDisplay } from "./LLMConfigDisplay";
import { BudgetUsageDisplay } from "./BudgetUsageDisplay";
import { useMemorySettings } from "./useMemorySettings";

export function MemorySettingsModal({ isOpen, onClose }: { isOpen: boolean; onClose: () => void }) {
  const {
    usage,
    loading,
    saving,
    error,
    saved,
    llmConfig,
    enabled,
    setEnabled,
    budgetEnabled,
    setBudgetEnabled,
    budget,
    setBudget,
    maxMandates,
    setMaxMandates,
    maxGuardrails,
    setMaxGuardrails,
    referenceIndexEnabled,
    setReferenceIndexEnabled,
    handleSave,
  } = useMemorySettings(isOpen, onClose);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center" data-testid="settings-modal">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-white dark:bg-slate-900 shadow-2xl">
        <ModalHeader onClose={onClose} />
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
              <ToggleSetting
                label="Memory Injection"
                enabled={enabled}
                onToggle={() => setEnabled(!enabled)}
                activeIcon={Power}
                inactiveIcon={Power}
                activeLabel="Active"
                inactiveLabel="Disabled"
                activeDescription="Memories are injected into context"
                inactiveDescription="No memories will be injected (kill switch)"
                variant="danger"
              />

              {enabled && (
                <>
                  <ToggleSetting
                    label="Budget Enforcement"
                    enabled={budgetEnabled}
                    onToggle={() => setBudgetEnabled(!budgetEnabled)}
                    activeIcon={ToggleRight}
                    inactiveIcon={ToggleLeft}
                    activeLabel="Limited"
                    inactiveLabel="Unlimited"
                    activeDescription={`Limit injection to ${budget.toLocaleString()} tokens`}
                    inactiveDescription="Inject all memories (no limit)"
                  />

                  {budgetEnabled && <TokenBudgetSlider budget={budget} onChange={setBudget} />}

                  <div className="space-y-4">
                    <div className="flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
                      <Gauge className="w-4 h-4" />
                      Per-Tier Injection Limits
                    </div>
                    <p className="text-xs text-slate-500 -mt-2">
                      Set maximum items per tier (0 = unlimited)
                    </p>
                    <TierLimitSlider
                      label="Mandates"
                      icon={Shield}
                      value={maxMandates}
                      max={usage?.mandates_total || 20}
                      onChange={setMaxMandates}
                      colorClass="text-emerald-600 dark:text-emerald-400"
                      borderColorClass="border-emerald-200 dark:border-emerald-800"
                      bgColorClass="bg-emerald-50/50 dark:bg-emerald-900/10"
                      accentColorClass="accent-emerald-600"
                    />
                    <TierLimitSlider
                      label="Guardrails"
                      icon={AlertTriangle}
                      value={maxGuardrails}
                      max={usage?.guardrails_total || 20}
                      onChange={setMaxGuardrails}
                      colorClass="text-amber-600 dark:text-amber-400"
                      borderColorClass="border-amber-200 dark:border-amber-800"
                      bgColorClass="bg-amber-50/50 dark:bg-amber-900/10"
                      accentColorClass="accent-amber-600"
                    />
                  </div>

                  <ToggleSetting
                    label="Reference Index"
                    enabled={referenceIndexEnabled}
                    onToggle={() => setReferenceIndexEnabled(!referenceIndexEnabled)}
                    activeIcon={ToggleRight}
                    inactiveIcon={ToggleLeft}
                    activeLabel="Enabled"
                    inactiveLabel="Disabled"
                    activeDescription="TOON compressed index for reference discoverability (~800 tokens)"
                    inactiveDescription="No reference index injected"
                    variant="sky"
                  />

                  {llmConfig && <LLMConfigDisplay config={llmConfig} />}
                  {usage && (
                    <BudgetUsageDisplay
                      usage={usage}
                      referenceIndexEnabled={referenceIndexEnabled}
                    />
                  )}
                </>
              )}
            </>
          )}
        </div>
        <ModalFooter
          onClose={onClose}
          onSave={handleSave}
          loading={loading}
          saving={saving}
          saved={saved}
        />
      </div>
    </div>
  );
}
