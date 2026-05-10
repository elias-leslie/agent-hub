import { cn } from '@/lib/utils'
import styles from './runtime-context.module.css'

type Tier =
  | 'mandate'
  | 'guardrail'
  | 'capability'
  | 'reference'
  | 'archive'
  | 'prompt'

const TIER_CLASS: Record<Tier, string> = {
  mandate: styles.tierMandate,
  guardrail: styles.tierGuardrail,
  capability: styles.tierReference,
  reference: styles.tierReference,
  archive: styles.tierArchive,
  prompt: styles.tierPrompt,
}

const TIER_ABBR: Record<Tier, string> = {
  mandate: 'MND',
  guardrail: 'GRD',
  capability: 'REF',
  reference: 'REF',
  archive: 'ARC',
  prompt: 'SYS',
}

export function TypeChip({
  kind,
  tier,
  label,
}: {
  kind: 'memory' | 'prompt'
  tier: Tier
  label?: string
}) {
  const isMemory = kind === 'memory'
  const text = label ?? `${isMemory ? 'MEM' : 'PRM'}·${TIER_ABBR[tier]}`
  return (
    <span
      className={cn(
        styles.typechip,
        isMemory ? styles.typechipMem : styles.typechipPrm,
      )}
    >
      <span className={cn(styles.tierDot, TIER_CLASS[tier])} />
      {text}
    </span>
  )
}
