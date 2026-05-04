import { useEffect, useState } from 'react'
import {
  getBudgetUsage,
  getLLMConfig,
  getSettings,
  type LLMConfig,
  type MemoryBudgetUsage,
  type MemorySettings,
  updateSettings,
} from '@/lib/api/memory-settings'

export function useMemorySettings(isOpen: boolean, onClose: () => void) {
  const [settings, setSettings] = useState<MemorySettings | null>(null)
  const [usage, setUsage] = useState<MemoryBudgetUsage | null>(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [llmConfig, setLlmConfig] = useState<LLMConfig | null>(null)

  const [enabled, setEnabled] = useState(true)
  const [continuityEnabled, setContinuityEnabled] = useState(true)
  const [continuityMaxSessions, setContinuityMaxSessions] = useState(5)

  useEffect(() => {
    if (isOpen) loadData()
  }, [isOpen])

  async function loadData() {
    setLoading(true)
    setError(null)
    try {
      const [settingsData, usageData, llmData] = await Promise.all([
        getSettings(),
        getBudgetUsage(),
        getLLMConfig().catch(() => null),
      ])
      setSettings(settingsData)
      setUsage(usageData)
      setLlmConfig(llmData)
      setEnabled(settingsData.enabled)
      setContinuityEnabled(settingsData.continuity_enabled)
      setContinuityMaxSessions(settingsData.continuity_max_sessions)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to load settings')
    } finally {
      setLoading(false)
    }
  }

  async function handleSave() {
    setSaving(true)
    setError(null)
    try {
      const updated = await updateSettings({
        enabled,
        continuity_enabled: continuityEnabled,
        continuity_max_sessions: continuityMaxSessions,
      })
      setSettings(updated)
      setSaved(true)
      setTimeout(() => onClose(), 800)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to save settings')
    } finally {
      setSaving(false)
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
    continuityEnabled,
    setContinuityEnabled,
    continuityMaxSessions,
    setContinuityMaxSessions,
    handleSave,
  }
}
