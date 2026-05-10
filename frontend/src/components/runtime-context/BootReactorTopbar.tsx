'use client'

import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { PolicySettingsPanel } from './PolicySettingsPanel'
import styles from './runtime-context.module.css'
import { TokenGauge } from './TokenGauge'

interface ProjectOption {
  id: string
  label: string
}

interface Props {
  used: number
  budget: number
  onRefresh: () => void
  onReset: () => void
  refreshing?: boolean
  resetting?: boolean
  hasOverrides: boolean
  // Profile whose injection caps the policy panel edits. This surface is
  // CLI/TUI boot context only (Codex/Claude/Gemini session start), so callers
  // pass `agent_startup` here. Other profiles (agent_coding, agent_visual,
  // etc.) are edited via the per-agent memory config instead — do not widen
  // this topbar to other profiles.
  profile: string
  // Project picker — empty array hides the select.
  projects?: ProjectOption[]
  selectedProjectId?: string | null
  onProjectChange?: (projectId: string | null) => void
}

export function BootReactorTopbar({
  used,
  budget,
  onRefresh,
  onReset,
  refreshing,
  resetting,
  hasOverrides,
  profile,
  projects = [],
  selectedProjectId,
  onProjectChange,
}: Props) {
  return (
    <header className={styles.topbar}>
      <div className={styles.crumb}>
        <span className={styles.dot} />
        <span>Agent Hub</span>
        <span className={styles.sep}>/</span>
        <span>Runtime Context</span>
        <span className={styles.pg}>
          — <em>boot reactor</em>
        </span>
      </div>
      <div className={styles.sepV} />
      <TokenGauge used={used} budget={budget} />
      {projects.length > 0 && onProjectChange ? (
        <label className={styles.projectPicker} title="Preview as project">
          <span className={styles.projectPickerLabel}>Project</span>
          <select
            className={styles.projectSelect}
            value={selectedProjectId ?? ''}
            onChange={(event) => {
              const next = event.target.value
              onProjectChange(next || null)
            }}
            aria-label="Project context"
          >
            <option value="">No project (global)</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.label}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className={styles.tools}>
        <PolicySettingsPanel profile={profile} />
        <button
          type="button"
          className={styles.btn}
          onClick={onReset}
          disabled={!hasOverrides || resetting}
          title="Drop all overrides and return to tier-rule defaults"
        >
          {resetting ? 'Resetting…' : 'Reset overrides'}
        </button>
        <button
          type="button"
          className={cn(styles.btn, styles.btnPrimary)}
          onClick={onRefresh}
          disabled={refreshing}
        >
          <RefreshCw
            width={12}
            height={12}
            className={refreshing ? styles.spinning : undefined}
          />
          Refresh
        </button>
      </div>
    </header>
  )
}
