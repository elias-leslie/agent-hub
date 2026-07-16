'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import { Check, Copy, Eye } from 'lucide-react'
import { useState } from 'react'
import type { RuntimeContextBlock } from '@/lib/api/runtime-context'
import { cn } from '@/lib/utils'
import { BlockRow } from './BlockRow'
import { ComputedRow } from './ComputedRow'
import { RenderedPreviewModal } from './RenderedPreviewModal'
import { blockKey, type EffectiveRenderMode } from './resolver'
import styles from './runtime-context.module.css'

interface Props {
  blocks: RuntimeContextBlock[]
  excluded: RuntimeContextBlock[]
  saving?: boolean
  fullContentLookup: Map<string, string>
  rendered: string
  // Auxiliary blocks computed at session start. Empty strings render nothing.
  projectIndex: string
  continuity: string
  toolCapabilities: string
  totalTokens: number
  budgetTokens: number
  budgetEnabled: boolean
  onExclude: (block: RuntimeContextBlock) => void
  onRestore: (block: RuntimeContextBlock) => void
  onEdit?: (block: RuntimeContextBlock) => void
  onRenderModeChange: (
    block: RuntimeContextBlock,
    mode: EffectiveRenderMode,
  ) => void
  onRemoveDefault?: (block: RuntimeContextBlock) => void
  isCrossPaneDragging?: boolean
}

function tokenSum(blocks: RuntimeContextBlock[]): number {
  return blocks.reduce((sum, block) => sum + block.token_count, 0)
}

function authorityRank(block: RuntimeContextBlock): number {
  if (block.prompt_type === 'global_guardrail' || block.tier === 'guardrail') {
    return 0
  }
  if (block.prompt_type === 'global_mandate' || block.tier === 'mandate') {
    return 1
  }
  if (block.source_type === 'prompt') return 2
  return 3
}

export function RenderedPane({
  blocks,
  excluded,
  saving,
  fullContentLookup,
  rendered,
  projectIndex,
  continuity,
  toolCapabilities,
  totalTokens,
  budgetTokens,
  budgetEnabled,
  onExclude,
  onRestore,
  onEdit,
  onRenderModeChange,
  onRemoveDefault,
  isCrossPaneDragging,
}: Props) {
  const [previewOpen, setPreviewOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  // Full text the agent actually sees: authority-ordered operator context first.
  const fullRendered = [rendered, projectIndex, continuity, toolCapabilities]
    .filter((chunk) => chunk && chunk.trim().length > 0)
    .join('\n')
  const handleCopy = async () => {
    if (!fullRendered) return
    await navigator.clipboard.writeText(fullRendered)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }
  const auto = blocks.filter((block) => block.source === 'auto')
  const pinned = blocks.filter((block) => block.source === 'pinned')
  // Pane numbers come from per-block token counts so the header and footer
  // reconcile with the inline row counts. The topbar gauge separately reports
  // the fully rendered prompt cost (which includes template overhead between
  // blocks).
  const blockTokens = tokenSum(blocks)

  const dropZone = useDroppable({
    id: 'rendered-zone',
    data: { kind: 'rendered-zone' },
  })

  // Single position-ordered list mixing auto / pinned / excluded — each row's
  // own AUTO / PINNED / EXCLUDED badge (and dimmed style on excluded) carries
  // the distinction inline, so there are no separate sections to scroll past.
  // Excluded rows participate in the SortableContext so the user can drag
  // them around without restoring; their mode='exclude' is preserved on save.
  const excludedKeys = new Set(excluded.map(blockKey))
  const ordered = [...blocks, ...excluded].sort(
    (a, b) => authorityRank(a) - authorityRank(b) || a.position - b.position,
  )
  const sortableIds = ordered.map(
    (block) => `rendered:${block.source_type}:${block.source_id}`,
  )

  return (
    <section
      className={cn(styles.pane, styles.paneLive)}
      aria-label="Rendered boot context"
    >
      <header className={styles.paneHead}>
        <div className={styles.paneTitle}>
          <h2>
            <em>Rendered</em>
          </h2>
          <span className={styles.paneSub}>burn chamber · injection order</span>
        </div>
        <div />
        <div className={styles.tools}>
          <span className={styles.paneStat}>
            <span className="lo">blocks </span>
            {blocks.length}
            <span className="lo"> · </span>
            {saving ? 'saving…' : `${blockTokens.toLocaleString()} tok`}
          </span>
          <button
            type="button"
            className={styles.btn}
            onClick={() => setPreviewOpen(true)}
            disabled={!fullRendered}
            title="Preview the verbatim rendered context shown to CLI/TUI agents"
          >
            <Eye width={12} height={12} />
            Preview
          </button>
          <button
            type="button"
            className={styles.btn}
            onClick={handleCopy}
            disabled={!fullRendered}
            title="Copy the rendered context to the clipboard"
          >
            {copied ? (
              <>
                <Check width={12} height={12} />
                Copied
              </>
            ) : (
              <>
                <Copy width={12} height={12} />
                Copy
              </>
            )}
          </button>
        </div>
      </header>

      <SortableContext
        items={sortableIds}
        strategy={verticalListSortingStrategy}
      >
        <div
          ref={dropZone.setNodeRef}
          className={cn(
            styles.rows,
            (dropZone.isOver || isCrossPaneDragging) && styles.rowsDropTarget,
          )}
        >
          {ordered.length === 0 &&
          !projectIndex &&
          !continuity &&
          !toolCapabilities ? (
            <div className={styles.empty}>
              {isCrossPaneDragging ? 'Drop to pin' : 'No blocks resolved.'}
            </div>
          ) : null}
          {ordered.map((block) => {
            const isExcluded = excludedKeys.has(blockKey(block))
            return (
              <BlockRow
                key={`rendered:${block.source_type}:${block.source_id}`}
                block={block}
                variant="rendered"
                excluded={isExcluded}
                fullContent={fullContentLookup.get(
                  `${block.source_type}:${block.source_id}`,
                )}
                onExclude={isExcluded ? undefined : onExclude}
                onRestore={isExcluded ? onRestore : undefined}
                onEdit={onEdit}
                onRenderModeChange={onRenderModeChange}
                onRemoveDefault={onRemoveDefault}
              />
            )
          })}
          {projectIndex ? (
            <ComputedRow
              slug="project-index"
              title="Project Index"
              content={projectIndex}
              tokenCount={Math.max(1, Math.round(projectIndex.length / 4))}
            />
          ) : null}
          {continuity ? (
            <ComputedRow
              slug="continuity"
              title="Continuity"
              content={continuity}
              tokenCount={Math.max(1, Math.round(continuity.length / 4))}
            />
          ) : null}
          {toolCapabilities ? (
            <ComputedRow
              slug="tool-capabilities"
              title="Tool Capabilities"
              content={toolCapabilities}
              tokenCount={Math.max(1, Math.round(toolCapabilities.length / 4))}
            />
          ) : null}
        </div>
      </SortableContext>

      <footer className={styles.paneFoot}>
        <span>
          <span className="num">{blockTokens.toLocaleString()}</span> tok ·{' '}
          <span className="num">{blocks.length}</span> active ·{' '}
          <span className="num">{excluded.length}</span> excluded
        </span>
        <span>
          Auto {auto.length} · Pinned {pinned.length} · Excluded{' '}
          {excluded.length}
        </span>
      </footer>
      {previewOpen ? (
        <RenderedPreviewModal
          rendered={rendered}
          projectIndex={projectIndex}
          continuity={continuity}
          toolCapabilities={toolCapabilities}
          totalTokens={totalTokens}
          budgetTokens={budgetTokens}
          budgetEnabled={budgetEnabled}
          onClose={() => setPreviewOpen(false)}
        />
      ) : null}
    </section>
  )
}
