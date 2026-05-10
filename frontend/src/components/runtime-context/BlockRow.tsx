'use client'

import {
  type DraggableAttributes,
  type DraggableSyntheticListeners,
  useDraggable,
  useDroppable,
} from '@dnd-kit/core'
import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  Archive,
  ChevronDown,
  Pencil,
  Plus,
  RotateCcw,
  Star,
  X,
} from 'lucide-react'
import { useState } from 'react'
import type { RuntimeContextBlock } from '@/lib/api/runtime-context'
import { cn } from '@/lib/utils'
import { RenderModeMenu } from './RenderModeMenu'
import {
  type EffectiveRenderMode,
  effectiveRenderMode,
  isFullRender,
} from './resolver'
import styles from './runtime-context.module.css'
import { TypeChip } from './TypeChip'

type Tier =
  | 'mandate'
  | 'guardrail'
  | 'capability'
  | 'reference'
  | 'archive'
  | 'prompt'

function tierFromBlock(block: RuntimeContextBlock): Tier {
  if (block.source_type === 'prompt') return 'prompt'
  const t = block.tier ?? block.render_tier ?? 'reference'
  if (
    t === 'mandate' ||
    t === 'guardrail' ||
    t === 'reference' ||
    t === 'capability' ||
    t === 'archive'
  ) {
    return t
  }
  return 'reference'
}

function chevronLabel(
  variant: 'rendered' | 'library',
  isPrompt: boolean,
  expanded: boolean,
): string {
  if (variant === 'library')
    return expanded ? 'Collapse content' : 'Show content'
  if (isPrompt) return expanded ? 'Hide prompt body' : 'Show prompt body'
  return expanded ? 'Show rendered version' : 'Expand to full content'
}

function shortHash(block: RuntimeContextBlock): string {
  if (block.source_type === 'prompt') return `prompt:${block.source_id}`
  const tag =
    block.tier === 'mandate' ? 'M' : block.tier === 'guardrail' ? 'G' : 'M'
  return `${tag}:${block.source_id.slice(0, 8)}`
}

interface BlockRowProps {
  block: RuntimeContextBlock
  variant: 'rendered' | 'library'
  inContext?: boolean
  excluded?: boolean
  // Raw full content for compact/summary memory blocks, looked up from the
  // library cache. When the user expands the chevron, the body's text swaps
  // from block.content (compact rendering) to this full content in place.
  fullContent?: string
  onPin?: (block: RuntimeContextBlock) => void
  onExclude?: (block: RuntimeContextBlock) => void
  onRestore?: (block: RuntimeContextBlock) => void
  onEdit?: (block: RuntimeContextBlock) => void
  onRenderModeChange?: (
    block: RuntimeContextBlock,
    mode: EffectiveRenderMode,
  ) => void
  // Source-of-truth edits — change the underlying prompt/memory record so the
  // default behavior shifts globally, not just for this profile.
  onMakeDefault?: (block: RuntimeContextBlock) => void
  onRemoveDefault?: (block: RuntimeContextBlock) => void
}

export function BlockRow(props: BlockRowProps) {
  if (props.variant === 'rendered') {
    return <RenderedRow {...props} />
  }
  return <LibraryRow {...props} />
}

function RowBody({
  block,
  variant,
  excluded,
  expanded,
  setExpanded,
  fullContent,
  onPin,
  onExclude,
  onRestore,
  onEdit,
  onRenderModeChange,
  onMakeDefault,
  onRemoveDefault,
  inContext,
  dragHandleProps,
}: BlockRowProps & {
  expanded: boolean
  setExpanded: (value: boolean) => void
  dragHandleProps?: {
    attributes?: DraggableAttributes
    listeners?: DraggableSyntheticListeners
  }
}) {
  const tier = tierFromBlock(block)
  const mode = effectiveRenderMode(block)
  const showMode = block.source_type === 'memory' && variant === 'rendered'
  const auto = block.source === 'auto'
  const pinned = block.source === 'pinned'
  const fullRender = isFullRender(block)
  const isPrompt = block.source_type === 'prompt'
  // Rendered memory: body always visible, chevron swaps compact↔full when applicable.
  // Rendered prompt: body collapsed by default, chevron toggles visibility (no swap).
  // Library: body collapsed by default; chevron always present for inspection.
  const showRenderedBody =
    variant === 'rendered' && !excluded && (!isPrompt || expanded)
  const showLibraryBody = variant === 'library' && expanded
  const showBody = showRenderedBody || showLibraryBody
  const renderedSwap =
    variant === 'rendered' && !fullRender && !isPrompt && expanded
  const renderedChevron =
    variant === 'rendered' && !excluded && (isPrompt || !fullRender)
  // In-context library rows are inert (pointer-events: none on the row),
  // so the chevron wouldn't be interactive — hide it and let the IN CONTEXT
  // pill claim the right column.
  const libraryChevron = variant === 'library' && !inContext
  const showChevron = renderedChevron || libraryChevron
  const bodyText = renderedSwap ? (fullContent ?? block.content) : block.content
  // AUTO/PINNED/EXCLUDED reflect runtime placement, not library cataloguing.
  // On library rows the `source` field is a synthetic mapping that doesn't
  // describe whether the block is currently in context, so suppress it there.
  const showStateBadge = variant === 'rendered'
  const showLibraryTools = variant === 'library' && !inContext
  // Source-of-truth toggles. "Make default" is offered on library rows that
  // aren't already auto-eligible (prompt missing boot_eligible, or memory in a
  // non-default tier like reference/archive). "Remove default" is offered on
  // rendered auto rows so users can demote the underlying record to archive
  // (memory) / clear boot_eligible (prompt).
  const isPromptBootDefault = isPrompt && block.auto_reason === 'boot_eligible'
  const isMemoryDefaultTier =
    block.source_type === 'memory' &&
    (block.tier === 'mandate' || block.tier === 'guardrail')
  const showMakeDefault =
    variant === 'library' &&
    !inContext &&
    !!onMakeDefault &&
    !(isPromptBootDefault || isMemoryDefaultTier)
  const showRemoveDefault =
    variant === 'rendered' &&
    !excluded &&
    !!onRemoveDefault &&
    block.source === 'auto' &&
    (isPromptBootDefault || block.source_type === 'memory')
  return (
    <>
      <div
        className={styles.grip}
        {...(dragHandleProps?.attributes ?? {})}
        {...(dragHandleProps?.listeners ?? {})}
        title="Drag to reorder or unpin"
      >
        <span />
        <span />
        <span />
      </div>
      <TypeChip kind={block.source_type} tier={tier} />
      <div className={styles.ttlblock}>
        <div className={styles.ttl}>{block.title}</div>
        <div className={styles.meta}>
          {showStateBadge ? (
            excluded ? (
              <span className={styles.metaExcluded}>EXCLUDED</span>
            ) : auto ? (
              <span className={styles.metaAuto}>AUTO</span>
            ) : pinned ? (
              <span className={styles.metaPin}>PINNED</span>
            ) : null
          ) : null}
          {renderedSwap ? <span className={styles.metaFull}>FULL</span> : null}
          {block.scope ? (
            <span className={styles.metaScope}>{block.scope}</span>
          ) : null}
          <span className={styles.metaHash}>{shortHash(block)}</span>
          {(block.tags ?? []).slice(0, 3).map((tag) => (
            <span key={tag} className={styles.metaTag}>
              {tag}
            </span>
          ))}
        </div>
      </div>
      <div className={styles.tools}>
        {variant === 'library' && inContext ? (
          <span className={styles.inContextPill}>IN CONTEXT</span>
        ) : null}
        {!(variant === 'library' && inContext) ? (
          <div className={styles.tok}>
            {block.token_count}
            <span className="u">tok</span>
          </div>
        ) : null}
        {showMode && !excluded && onRenderModeChange ? (
          <RenderModeMenu
            value={mode}
            onChange={(value) => onRenderModeChange(block, value)}
          />
        ) : null}
        {onEdit && !(variant === 'library' && inContext) ? (
          <button
            type="button"
            className={styles.iconbtn}
            onClick={() => onEdit(block)}
            title={
              block.source_type === 'prompt' ? 'Edit prompt' : 'Edit memory'
            }
            aria-label={
              block.source_type === 'prompt' ? 'Edit prompt' : 'Edit memory'
            }
          >
            <Pencil width={12} height={12} />
          </button>
        ) : null}
        {showChevron ? (
          <button
            type="button"
            className={cn(styles.iconbtn, expanded && 'on')}
            onClick={() => setExpanded(!expanded)}
            title={chevronLabel(variant, isPrompt, expanded)}
            aria-expanded={expanded}
            aria-label={chevronLabel(variant, isPrompt, expanded)}
          >
            <ChevronDown
              width={13}
              height={13}
              className={cn(styles.chev, expanded && styles.chevOpen)}
            />
          </button>
        ) : null}
        {variant === 'rendered' && !excluded && onExclude ? (
          <button
            type="button"
            className={cn(styles.iconbtn, 'danger')}
            onClick={() => onExclude(block)}
            title="Exclude from boot context"
          >
            <X width={13} height={13} />
          </button>
        ) : null}
        {variant === 'rendered' && excluded && onRestore ? (
          <button
            type="button"
            className={styles.iconbtn}
            onClick={() => onRestore(block)}
            title="Restore"
          >
            <RotateCcw width={13} height={13} />
          </button>
        ) : null}
        {showMakeDefault && onMakeDefault ? (
          <button
            type="button"
            className={styles.iconbtn}
            onClick={() => onMakeDefault(block)}
            aria-label={
              isPrompt
                ? 'Mark prompt boot-eligible (global default)'
                : 'Set memory tier to mandate (global default)'
            }
            title={
              isPrompt
                ? 'Make boot-eligible — appears at session start for every agent'
                : 'Promote to mandate tier — appears for every agent (use Edit for guardrail/reference)'
            }
          >
            <Star width={12} height={12} />
          </button>
        ) : null}
        {showRemoveDefault && onRemoveDefault ? (
          <button
            type="button"
            className={cn(styles.iconbtn, 'danger')}
            onClick={() => onRemoveDefault(block)}
            aria-label={
              isPrompt
                ? 'Remove prompt from global boot defaults'
                : 'Archive memory (removes from any session-start injection)'
            }
            title={
              isPrompt
                ? 'Remove from global boot defaults — clears boot_eligible'
                : 'Archive memory — sets tier to archive everywhere'
            }
          >
            <Archive width={12} height={12} />
          </button>
        ) : null}
        {showLibraryTools && onPin ? (
          <button
            type="button"
            className={styles.pinBtn}
            onClick={() => onPin(block)}
            title="Pin to boot context"
          >
            <Plus width={11} height={11} /> Pin
          </button>
        ) : null}
      </div>
      {showBody ? (
        <div
          className={styles.bodyInline}
          data-testid={
            variant === 'rendered' ? 'rendered-body-inline' : 'library-body'
          }
        >
          {bodyText}
        </div>
      ) : null}
    </>
  )
}

function RenderedRow(props: BlockRowProps) {
  const { block, excluded } = props
  const [expanded, setExpanded] = useState(false)
  const sortable = useSortable({
    id: `rendered:${block.source_type}:${block.source_id}`,
    data: { kind: 'rendered', block },
  })
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(sortable.transform),
    transition: sortable.transition,
  }
  return (
    <div
      ref={sortable.setNodeRef}
      style={style}
      className={cn(
        styles.row,
        excluded && styles.rowExcluded,
        sortable.isDragging && styles.rowDragging,
        sortable.isOver && !sortable.isDragging && styles.rowDropTarget,
        expanded && !excluded && styles.rowExpanded,
      )}
    >
      <RowBody
        {...props}
        expanded={expanded}
        setExpanded={setExpanded}
        dragHandleProps={{
          attributes: sortable.attributes,
          listeners: sortable.listeners,
        }}
      />
    </div>
  )
}

function LibraryRow(props: BlockRowProps) {
  const { block, inContext } = props
  const [expanded, setExpanded] = useState(false)
  const draggable = useDraggable({
    id: `library:${block.source_type}:${block.source_id}`,
    data: { kind: 'library', block },
    disabled: inContext,
  })
  const droppable = useDroppable({
    id: `lib-row:${block.source_type}:${block.source_id}`,
    data: { kind: 'library' },
    disabled: inContext,
  })
  const style: React.CSSProperties = {
    transform: CSS.Translate.toString(draggable.transform),
  }
  const setRefs = (node: HTMLDivElement | null) => {
    draggable.setNodeRef(node)
    droppable.setNodeRef(node)
  }
  return (
    <div
      ref={setRefs}
      style={style}
      className={cn(
        styles.row,
        styles.rowLib,
        inContext && styles.rowInContext,
        draggable.isDragging && styles.rowDragging,
        expanded && styles.rowExpanded,
      )}
    >
      <RowBody
        {...props}
        expanded={expanded}
        setExpanded={setExpanded}
        dragHandleProps={{
          attributes: draggable.attributes,
          listeners: draggable.listeners,
        }}
      />
    </div>
  )
}
