import { useState, useEffect } from "react";
import {
  getSettings,
  updateSettings,
  getBudgetUsage,
  getLLMConfig,
  type MemorySettings,
  type BudgetUsage,
  type LLMConfig,
} from "@/lib/api/memory-settings";

export function useMemorySettings(isOpen: boolean, onClose: () => void) {
  const [settings, setSettings] = useState<MemorySettings | null>(null);
  const [usage, setUsage] = useState<BudgetUsage | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null);

  const [enabled, setEnabled] = useState(true);
  const [budgetEnabled, setBudgetEnabled] = useState(true);
  const [budget, setBudget] = useState(2000);
  const [maxMandates, setMaxMandates] = useState(0);
  const [maxGuardrails, setMaxGuardrails] = useState(0);
  const [referenceIndexEnabled, setReferenceIndexEnabled] = useState(true);

  useEffect(() => {
    if (isOpen) loadData();
  }, [isOpen]);

  async function loadData() {
    setLoading(true);
    setError(null);
    try {
      const [settingsData, usageData, llmData] = await Promise.all([
        getSettings(),
        getBudgetUsage(),
        getLLMConfig().catch(() => null),
      ]);
      setSettings(settingsData);
      setUsage(usageData);
      setLlmConfig(llmData);
      setEnabled(settingsData.enabled);
      setBudgetEnabled(settingsData.budget_enabled);
      setBudget(settingsData.total_budget);
      setMaxMandates(settingsData.max_mandates ?? 0);
      setMaxGuardrails(settingsData.max_guardrails ?? 0);
      setReferenceIndexEnabled(settingsData.reference_index_enabled ?? true);
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
        max_mandates: maxMandates,
        max_guardrails: maxGuardrails,
        reference_index_enabled: referenceIndexEnabled,
      });
      setSettings(updated);
      setSaved(true);
      setTimeout(() => onClose(), 800);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  return {
    settings,
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
  };
}
