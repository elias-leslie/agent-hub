'use client'

import { History, Power } from 'lucide-react'
import { BudgetUsageDisplay } from './BudgetUsageDisplay'
import { LLMConfigDisplay } from './LLMConfigDisplay'
import { ModalFooter } from './ModalFooter'
import { ModalHeader } from './ModalHeader'
import { ToggleSetting } from './ToggleSetting'
import { useMemorySettings } from './useMemorySettings'

export function MemorySettingsModal({
  isOpen,
  onClose,
}: {
  isOpen: boolean
  onClose: () => void
}) {
  const {
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
  } = useMemorySettings(isOpen, onClose)

  if (!isOpen) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      data-testid="settings-modal"
    >
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative w-full max-w-md mx-4 rounded-xl bg-slate-900 shadow-2xl">
        <ModalHeader onClose={onClose} />
        <div className="p-4 space-y-6">
          {loading ? (
            <div className="flex items-center justify-center py-8">
              <div className="w-6 h-6 border-2 border-blue-600 border-t-transparent rounded-full animate-spin" />
            </div>
          ) : error ? (
            <div className="p-3 rounded-lg bg-red-900/20 text-red-400 text-sm">
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
                    label="Session Continuity"
                    enabled={continuityEnabled}
                    onToggle={() => setContinuityEnabled(!continuityEnabled)}
                    activeIcon={History}
                    inactiveIcon={History}
                    activeLabel="Enabled"
                    inactiveLabel="Disabled"
                    activeDescription="Recent Activity block injected into context"
                    inactiveDescription="No cross-session continuity"
                    variant="violet"
                  />

                  {continuityEnabled && (
                    <div className="space-y-2 pl-2">
                      <div className="flex items-center justify-between">
                        <label className="text-xs font-medium text-slate-400">
                          Max Sessions
                        </label>
                        <span className="text-xs font-mono text-slate-300">
                          {continuityMaxSessions}
                        </span>
                      </div>
                      <input
                        type="range"
                        min={1}
                        max={20}
                        step={1}
                        value={continuityMaxSessions}
                        onChange={(e) =>
                          setContinuityMaxSessions(parseInt(e.target.value, 10))
                        }
                        className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer accent-violet-600"
                      />
                      <div className="flex justify-between text-[10px] text-slate-400">
                        <span>1</span>
                        <span>10</span>
                        <span>20</span>
                      </div>
                    </div>
                  )}

                  {llmConfig && <LLMConfigDisplay config={llmConfig} />}
                  {usage && (
                    <BudgetUsageDisplay
                      usage={usage}
                      continuityEnabled={continuityEnabled}
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
  )
}
