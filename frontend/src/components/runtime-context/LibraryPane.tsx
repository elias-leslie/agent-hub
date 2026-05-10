'use client'

import { useDroppable } from '@dnd-kit/core'
import { Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import type { RuntimeContextBlock } from '@/lib/api/runtime-context'
import { cn } from '@/lib/utils'
import { BlockRow } from './BlockRow'
import { blockKey } from './resolver'
import styles from './runtime-context.module.css'

type FilterKey =
  | 'all'
  | 'memories'
  | 'prompts'
  | 'mandate'
  | 'guardrail'
  | 'reference'
  | 'archive'
  | 'in-context'

interface Props {
  library: RuntimeContextBlock[]
  inContextKeys: Set<string>
  onPin: (block: RuntimeContextBlock) => void
  onEdit?: (block: RuntimeContextBlock) => void
  onMakeDefault?: (block: RuntimeContextBlock) => void
  isCrossPaneDragging?: boolean
  totalCount: number
}

function chipMatches(
  filter: FilterKey,
  block: RuntimeContextBlock,
  isInContext: boolean,
): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'memories':
      return block.source_type === 'memory'
    case 'prompts':
      return block.source_type === 'prompt'
    case 'mandate':
      return block.source_type === 'memory' && block.tier === 'mandate'
    case 'guardrail':
      return block.source_type === 'memory' && block.tier === 'guardrail'
    case 'reference':
      return (
        block.source_type === 'memory' &&
        (block.tier === 'reference' || block.tier === 'capability')
      )
    case 'archive':
      return block.source_type === 'memory' && block.tier === 'archive'
    case 'in-context':
      return isInContext
  }
}

function searchMatches(needle: string, block: RuntimeContextBlock): boolean {
  if (!needle) return true
  const haystack = `${block.title} ${block.content} ${block.source_id} ${(block.tags ?? []).join(' ')}`
  return haystack.toLowerCase().includes(needle.toLowerCase())
}

export function LibraryPane({
  library,
  inContextKeys,
  onPin,
  onEdit,
  onMakeDefault,
  isCrossPaneDragging,
  totalCount,
}: Props) {
  const [activeFilters, setActiveFilters] = useState<Set<FilterKey>>(
    new Set(['all']),
  )
  const [search, setSearch] = useState('')

  const dropZone = useDroppable({
    id: 'library-zone',
    data: { kind: 'library-zone' },
  })

  const counts = useMemo(() => {
    let memories = 0
    let prompts = 0
    let mandate = 0
    let guardrail = 0
    let reference = 0
    let archive = 0
    let inContext = 0
    for (const block of library) {
      if (block.source_type === 'memory') {
        memories += 1
        if (block.tier === 'mandate') mandate += 1
        else if (block.tier === 'guardrail') guardrail += 1
        else if (block.tier === 'reference' || block.tier === 'capability')
          reference += 1
        else if (block.tier === 'archive') archive += 1
      } else {
        prompts += 1
      }
      if (inContextKeys.has(blockKey(block))) inContext += 1
    }
    return {
      memories,
      prompts,
      mandate,
      guardrail,
      reference,
      archive,
      inContext,
    }
  }, [library, inContextKeys])

  const filtered = useMemo(() => {
    const filters = activeFilters.has('all')
      ? new Set<FilterKey>(['all'])
      : activeFilters
    return library.filter((block) => {
      const inCtx = inContextKeys.has(blockKey(block))
      const matchesFilter = Array.from(filters).every((filter) =>
        chipMatches(filter, block, inCtx),
      )
      return matchesFilter && searchMatches(search, block)
    })
  }, [library, inContextKeys, activeFilters, search])

  const toggle = (key: FilterKey) => {
    setActiveFilters((prev) => {
      const next = new Set(prev)
      if (key === 'all') return new Set(['all'])
      if (next.has(key)) {
        next.delete(key)
        if (next.size === 0) next.add('all')
      } else {
        next.delete('all')
        next.add(key)
      }
      return next
    })
  }

  const Chip = ({
    id,
    label,
    n,
    color,
  }: {
    id: FilterKey
    label: string
    n: number
    color?: 'amber' | 'coral'
  }) => {
    const on = activeFilters.has(id)
    return (
      <button
        type="button"
        className={cn(
          styles.chip,
          on && styles.chipOn,
          on && color === 'amber' && styles.chipAmberOn,
          on && color === 'coral' && styles.chipCoralOn,
        )}
        onClick={() => toggle(id)}
      >
        {label} <span className={styles.chipN}>{n}</span>
      </button>
    )
  }

  return (
    <section className={styles.pane} aria-label="Library">
      <header className={styles.paneHead}>
        <div className={styles.paneTitle}>
          <h2>
            <em>Library</em>
          </h2>
          <span className={styles.paneSub}>
            fuel rack · {totalCount} blocks
          </span>
        </div>
        <div />
        <div className={styles.tools}>
          <span className={styles.paneStat}>
            <span className="lo">in context </span>
            {counts.inContext}
          </span>
        </div>
      </header>

      <div className={styles.libToolbar}>
        <div className={styles.search}>
          <Search width={13} height={13} />
          <input
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search library — name, content, tag…"
          />
        </div>
      </div>

      <div className={styles.chips}>
        <Chip id="all" label="All" n={library.length} />
        <Chip id="memories" label="Memories" n={counts.memories} />
        <Chip id="prompts" label="Prompts" n={counts.prompts} />
        <Chip id="mandate" label="Mandates" n={counts.mandate} color="coral" />
        <Chip
          id="guardrail"
          label="Guardrails"
          n={counts.guardrail}
          color="amber"
        />
        <Chip id="reference" label="References" n={counts.reference} />
        <Chip id="archive" label="Archive" n={counts.archive} />
        <Chip id="in-context" label="In context" n={counts.inContext} />
      </div>

      <div
        ref={dropZone.setNodeRef}
        className={cn(
          styles.libraryDropZone,
          (dropZone.isOver || isCrossPaneDragging) &&
            styles.libraryDropZoneActive,
        )}
      >
        <div className={styles.rows}>
          {filtered.length === 0 ? (
            <div className={styles.empty}>No matching blocks.</div>
          ) : null}
          {filtered.map((block) => (
            <BlockRow
              key={`library:${block.source_type}:${block.source_id}`}
              block={block}
              variant="library"
              inContext={inContextKeys.has(blockKey(block))}
              onPin={onPin}
              onEdit={onEdit}
              onMakeDefault={onMakeDefault}
            />
          ))}
        </div>
      </div>

      <footer className={styles.paneFoot}>
        <span>
          <span className="num">{library.length}</span> blocks ·{' '}
          <span className="num">{counts.memories}</span> mem ·{' '}
          <span className="num">{counts.prompts}</span> prm
        </span>
        <span>Drag → chamber to pin</span>
      </footer>
    </section>
  )
}
