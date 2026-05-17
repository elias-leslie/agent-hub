import { cn } from '@/lib/utils'
import styles from './runtime-context.module.css'

export function TokenGauge({
  used,
  budget,
  enabled,
}: {
  used: number
  budget: number
  enabled: boolean
}) {
  const safeBudget = enabled && budget > 0 ? budget : 0
  const ratio = safeBudget > 0 ? used / safeBudget : 0
  const pct = Math.round(ratio * 100)
  const overBudget = enabled && ratio > 1
  const widthPct = Math.min(Math.max(ratio, 0), 1) * 100
  return (
    <div className={styles.gauge} aria-label="Token gauge">
      <div className={styles.gaugeBar}>
        <div
          className={cn(styles.gaugeFill, overBudget && styles.gaugeOver)}
          style={{ width: `${widthPct}%` }}
        />
      </div>
      <div className={styles.gaugeReadout}>
        <span>{used.toLocaleString()}</span>
        {enabled ? (
          <>
            <span className="of"> / </span>
            <span className="lim">{safeBudget.toLocaleString()} tok</span>
            <span
              className={cn(styles.gaugePct, overBudget && styles.gaugePctOver)}
            >
              {pct}%
            </span>
          </>
        ) : (
          <span className="lim"> tok · budget off</span>
        )}
      </div>
    </div>
  )
}
