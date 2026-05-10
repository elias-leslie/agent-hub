import { cn } from '@/lib/utils'
import type { EffectiveRenderMode } from './resolver'
import styles from './runtime-context.module.css'

const MODE_CLASS: Record<EffectiveRenderMode, string> = {
  auto: styles.modeAuto,
  full: styles.modeFull,
  compact: styles.modeCompact,
  summary: styles.modeSummary,
}

const LABEL: Record<EffectiveRenderMode, string> = {
  auto: 'Auto',
  full: 'Full',
  compact: 'Compact',
  summary: 'Summary',
}

export function RenderModeMenu({
  value,
  onChange,
  disabled,
}: {
  value: EffectiveRenderMode
  onChange: (mode: EffectiveRenderMode) => void
  disabled?: boolean
}) {
  return (
    <select
      className={cn(styles.mode, MODE_CLASS[value])}
      value={value}
      disabled={disabled}
      onChange={(event) => onChange(event.target.value as EffectiveRenderMode)}
      aria-label="Render mode"
    >
      {(Object.keys(LABEL) as EffectiveRenderMode[]).map((mode) => (
        <option key={mode} value={mode}>
          {LABEL[mode]}
        </option>
      ))}
    </select>
  )
}
