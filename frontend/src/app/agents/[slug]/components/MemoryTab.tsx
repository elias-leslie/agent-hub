'use client'

import { Brain, Settings2 } from 'lucide-react'
import type { Agent } from '../types'
import { MemoryConfigSection } from './memory/MemoryConfigSection'
import { TagFilteringSection } from './memory/TagFilteringSection'
import { Toggle } from './memory/Toggle'
import type { MemoryConfig } from './memory/types'
import { cloneConfig, parseConfig } from './memory/utils'

interface MemoryTabProps {
  formData: Partial<Agent>
  updateField: <K extends keyof Agent>(field: K, value: Agent[K]) => void
}

export function MemoryTab({ formData, updateField }: MemoryTabProps) {
  const isCustomEnabled = formData.memory_config != null
  const effectiveSource = formData.effective_memory_config as
    | MemoryConfig
    | undefined

  if (!effectiveSource) {
    return null
  }

  const effectiveConfig = cloneConfig(effectiveSource)
  const config = isCustomEnabled
    ? formData.memory_config
      ? parseConfig(formData.memory_config, effectiveConfig)
      : cloneConfig(effectiveConfig)
    : cloneConfig(effectiveConfig)

  const updateConfig = (updates: Partial<MemoryConfig>) => {
    const newConfig = { ...config, ...updates }
    updateField('memory_config', newConfig)
  }

  const toggleCustomSettings = () => {
    if (isCustomEnabled) {
      updateField('memory_config', null)
    } else {
      updateField(
        'memory_config',
        cloneConfig(effectiveConfig) as Agent['memory_config'],
      )
    }
  }

  const handleUpdateTags = (
    field: 'audience_tags' | 'exclude_tags' | 'exclude_memory_uuids',
    tags: string[],
  ) => {
    if (isCustomEnabled) {
      updateConfig({ [field]: tags })
    } else {
      const candidateConfig = {
        ...effectiveConfig,
        [field]: tags,
      } as MemoryConfig
      const hasExplicitFilters =
        candidateConfig.audience_tags.length > 0 ||
        candidateConfig.exclude_tags.length > 0 ||
        candidateConfig.exclude_memory_uuids.length > 0

      if (!hasExplicitFilters) {
        updateField('memory_config', null)
      } else {
        updateField(
          'memory_config',
          candidateConfig as unknown as Agent['memory_config'],
        )
      }
    }
  }

  return (
    <div className="space-y-8">
      {/* Header */}
      <div>
        <h2 className="text-lg font-semibold text-slate-100 flex items-center gap-2">
          <Brain className="h-5 w-5 text-slate-400" />
          Memory Configuration
        </h2>
        <p className="text-sm text-slate-400 mt-1">
          Control how memory episodes are injected into this agent&apos;s
          context
        </p>
      </div>

      {/* Custom Settings Toggle */}
      <div className="flex items-center justify-between p-4 rounded-lg border border-slate-700 bg-slate-800/50">
        <div className="flex items-center gap-3">
          <Settings2 className="h-5 w-5 text-slate-400" />
          <div>
            <p className="text-sm font-medium text-slate-100">
              Enable Custom Memory Settings
            </p>
            <p className="text-xs text-slate-400">
              {isCustomEnabled
                ? 'Using per-agent memory configuration'
                : 'Using inherited memory baseline'}
            </p>
          </div>
        </div>
        <Toggle
          enabled={isCustomEnabled}
          onToggle={toggleCustomSettings}
          ariaLabel="Enable Custom Memory Settings"
        />
      </div>

      {/* Settings Panel */}
      <MemoryConfigSection
        config={config}
        isCustomEnabled={isCustomEnabled}
        onUpdateConfig={updateConfig}
      />

      {/* Tag Filtering Section */}
      <TagFilteringSection
        audienceTags={config.audience_tags}
        excludeTags={config.exclude_tags}
        excludeMemoryUuids={config.exclude_memory_uuids}
        onUpdateTags={handleUpdateTags}
      />
    </div>
  )
}
