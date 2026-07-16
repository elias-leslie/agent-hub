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
  const widthPct = Math.min(Math.max(ratio, 0), 1) * 100
  return (
    <div className={styles.gauge} aria-label="Token telemetry">
      <div className={styles.gaugeBar}>
        <div className={styles.gaugeFill} style={{ width: `${widthPct}%` }} />
      </div>
      <div className={styles.gaugeReadout}>
        <span>{used.toLocaleString()}</span>
        {enabled ? (
          <>
            <span className="of"> tok · target </span>
            <span className="lim">{safeBudget.toLocaleString()} tok</span>
            <span className={styles.gaugePct}>{pct}% · not enforced</span>
          </>
        ) : (
          <span className="lim"> tok · telemetry target off</span>
        )}
      </div>
    </div>
  )
}
