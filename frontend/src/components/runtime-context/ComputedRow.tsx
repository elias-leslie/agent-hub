'use client'

import { ChevronDown, Cpu } from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import styles from './runtime-context.module.css'

interface Props {
  // Stable identifier — "project-index" or "tool-capabilities".
  slug: string
  title: string
  content: string
  // Approximate; computed blocks aren't measured server-side per-block, only
  // the full concatenation goes into preview.total_tokens.
  tokenCount: number
}

export function ComputedRow({ slug, title, content, tokenCount }: Props) {
  const [expanded, setExpanded] = useState(false)
  return (
    <div
      className={cn(
        styles.row,
        styles.rowComputed,
        expanded && styles.rowExpanded,
      )}
      data-testid={`computed-row:${slug}`}
    >
      <div
        className={styles.computedIcon}
        title="Computed at session start — not user-editable"
      >
        <Cpu width={11} height={11} />
      </div>
      <span className={cn(styles.typechip, styles.typechipComputed)}>
        <span className={cn(styles.tierDot, styles.tierComputed)} />
        COMPUTED
      </span>
      <div className={styles.ttlblock}>
        <div className={styles.ttl}>{title}</div>
        <div className={styles.meta}>
          <span className={styles.metaComputed}>AUTO</span>
          <span className={styles.metaHash}>computed:{slug}</span>
        </div>
      </div>
      <div className={styles.tools}>
        <div className={styles.tok}>
          {tokenCount}
          <span className="u">tok</span>
        </div>
        <button
          type="button"
          className={cn(styles.iconbtn, expanded && 'on')}
          onClick={() => setExpanded(!expanded)}
          aria-expanded={expanded}
          aria-label={
            expanded ? 'Collapse computed block' : 'Expand computed block'
          }
          title={expanded ? 'Collapse' : 'Expand'}
        >
          <ChevronDown
            width={13}
            height={13}
            className={cn(styles.chev, expanded && styles.chevOpen)}
          />
        </button>
      </div>
      {expanded ? (
        <div
          className={styles.bodyInline}
          data-testid={`computed-body:${slug}`}
        >
          {content}
        </div>
      ) : null}
    </div>
  )
}
