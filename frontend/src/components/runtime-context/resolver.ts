import type {
  RuntimeContextBlock,
  RuntimeContextOverridePayload,
  RuntimeRenderMode,
  RuntimeSourceType,
  RuntimeTierOverride,
} from '@/lib/api/runtime-context'

export const RENDER_MODE_TO_TIER: Record<
  Exclude<RuntimeRenderMode | 'auto', 'auto'>,
  RuntimeTierOverride
> = {
  full: 'L2',
  compact: 'L1',
  summary: 'L0',
}

export const TIER_TO_RENDER_MODE: Record<
  RuntimeTierOverride,
  RuntimeRenderMode
> = {
  L2: 'full',
  L1: 'compact',
  L0: 'summary',
}

export type EffectiveRenderMode = RuntimeRenderMode | 'auto'

export function overrideKey(
  sourceType: RuntimeSourceType,
  sourceId: string,
): string {
  return `${sourceType}:${sourceId}`
}

export function blockKey(block: RuntimeContextBlock): string {
  return overrideKey(block.source_type, block.source_id)
}

function indexOverrides(
  overrides: RuntimeContextOverridePayload[],
): Map<string, RuntimeContextOverridePayload> {
  const map = new Map<string, RuntimeContextOverridePayload>()
  for (const item of overrides) {
    map.set(overrideKey(item.source_type, item.source_id), item)
  }
  return map
}

function nextPosition(
  blocks: RuntimeContextBlock[],
  overrides: RuntimeContextOverridePayload[],
): number {
  const maxBlock = blocks.reduce(
    (max, block) => Math.max(max, block.position),
    0,
  )
  const maxOverride = overrides.reduce(
    (max, item) => Math.max(max, item.position),
    0,
  )
  return Math.max(maxBlock, maxOverride, 0) + 10
}

function blankOverride(
  sourceType: RuntimeSourceType,
  sourceId: string,
  position: number,
): RuntimeContextOverridePayload {
  return {
    source_type: sourceType,
    source_id: sourceId,
    mode: 'order',
    position,
    enabled: true,
    note: null,
    tier_override: null,
  }
}

function withReplaced(
  overrides: RuntimeContextOverridePayload[],
  next: RuntimeContextOverridePayload,
): RuntimeContextOverridePayload[] {
  const key = overrideKey(next.source_type, next.source_id)
  const filtered = overrides.filter(
    (item) => overrideKey(item.source_type, item.source_id) !== key,
  )
  return [...filtered, next].sort((a, b) => a.position - b.position)
}

/** Pin a library block into the rendered pane.
 *  insertAtPosition lets the caller specify where in the order it lands;
 *  omit to append at the end. */
export function pinBlock(
  overrides: RuntimeContextOverridePayload[],
  blocks: RuntimeContextBlock[],
  sourceType: RuntimeSourceType,
  sourceId: string,
  insertAtPosition?: number,
): RuntimeContextOverridePayload[] {
  const map = indexOverrides(overrides)
  const existing = map.get(overrideKey(sourceType, sourceId))
  const position =
    insertAtPosition ?? existing?.position ?? nextPosition(blocks, overrides)
  return withReplaced(overrides, {
    ...blankOverride(sourceType, sourceId, position),
    mode: 'include',
    note: existing?.note ?? null,
    tier_override: existing?.tier_override ?? null,
  })
}

/** Drop a block out of the rendered pane back into library: clear its override entirely. */
export function unpinBlock(
  overrides: RuntimeContextOverridePayload[],
  sourceType: RuntimeSourceType,
  sourceId: string,
): RuntimeContextOverridePayload[] {
  const key = overrideKey(sourceType, sourceId)
  return overrides.filter(
    (item) => overrideKey(item.source_type, item.source_id) !== key,
  )
}

/** Mark a rendered block as excluded. */
export function excludeBlock(
  overrides: RuntimeContextOverridePayload[],
  blocks: RuntimeContextBlock[],
  block: RuntimeContextBlock,
): RuntimeContextOverridePayload[] {
  const map = indexOverrides(overrides)
  const existing = map.get(blockKey(block))
  const position =
    existing?.position ?? block.position ?? nextPosition(blocks, overrides)
  return withReplaced(overrides, {
    ...blankOverride(block.source_type, block.source_id, position),
    mode: 'exclude',
    note: existing?.note ?? null,
    tier_override: existing?.tier_override ?? null,
  })
}

/** Restore an excluded block: drop the override row entirely (so it falls back to
 *  whatever the tier rule / boot_eligible flag says), unless there's a tier_override
 *  worth keeping — in which case flip mode to 'order'. */
export function restoreBlock(
  overrides: RuntimeContextOverridePayload[],
  block: RuntimeContextBlock,
): RuntimeContextOverridePayload[] {
  const key = blockKey(block)
  const map = indexOverrides(overrides)
  const existing = map.get(key)
  if (!existing) return overrides
  if (existing.tier_override || existing.note) {
    return withReplaced(overrides, { ...existing, mode: 'order' })
  }
  return overrides.filter(
    (item) => overrideKey(item.source_type, item.source_id) !== key,
  )
}

/** Reorder rendered blocks. Caller passes the new ordered list; this function
 *  rewrites positions to (index + 1) * 10 and preserves any non-rendered overrides. */
export function reorderBlocks(
  overrides: RuntimeContextOverridePayload[],
  orderedBlocks: RuntimeContextBlock[],
): RuntimeContextOverridePayload[] {
  const orderedKeys = new Set(orderedBlocks.map(blockKey))
  const map = indexOverrides(overrides)
  const orderedOverrides = orderedBlocks.map((block, index) => {
    const existing = map.get(blockKey(block))
    // Preserve the existing override mode so excluded rows stay excluded and
    // pinned rows stay pinned across a reorder. Untracked auto rows fall back
    // to 'order', which is a position-only override.
    const mode =
      existing?.mode === 'include' || existing?.mode === 'exclude'
        ? existing.mode
        : 'order'
    return {
      source_type: block.source_type,
      source_id: block.source_id,
      mode,
      position: (index + 1) * 10,
      enabled: true,
      note: existing?.note ?? null,
      tier_override: existing?.tier_override ?? null,
    } satisfies RuntimeContextOverridePayload
  })
  const untouched = overrides.filter(
    (item) => !orderedKeys.has(overrideKey(item.source_type, item.source_id)),
  )
  return [...orderedOverrides, ...untouched].sort(
    (a, b) => a.position - b.position,
  )
}

/** Set the per-block render mode. 'auto' clears the tier_override; if the row has no
 *  other reason to exist (no exclude, no pin), the row is dropped entirely. */
export function setRenderMode(
  overrides: RuntimeContextOverridePayload[],
  block: RuntimeContextBlock,
  mode: EffectiveRenderMode,
): RuntimeContextOverridePayload[] {
  const key = blockKey(block)
  const map = indexOverrides(overrides)
  const existing = map.get(key)
  const tier = mode === 'auto' ? null : RENDER_MODE_TO_TIER[mode]
  if (
    tier === null &&
    (!existing || (existing.mode !== 'include' && existing.mode !== 'exclude'))
  ) {
    return overrides.filter(
      (item) => overrideKey(item.source_type, item.source_id) !== key,
    )
  }
  const merged: RuntimeContextOverridePayload = {
    source_type: block.source_type,
    source_id: block.source_id,
    mode: existing?.mode ?? 'order',
    position: existing?.position ?? block.position,
    enabled: existing?.enabled ?? true,
    note: existing?.note ?? null,
    tier_override: tier,
  }
  return withReplaced(overrides, merged)
}

export function effectiveRenderMode(
  block: RuntimeContextBlock,
): EffectiveRenderMode {
  if (block.tier_override) return TIER_TO_RENDER_MODE[block.tier_override]
  return 'auto'
}

/** Whether the block's `content` is already the full rendering, i.e. there is no
 *  fuller version to expand to. True for prompts (no compaction) and for memories
 *  whose effective render tier is L2. */
export function isFullRender(block: RuntimeContextBlock): boolean {
  if (block.source_type === 'prompt') return true
  if (block.tier_override === 'L2') return true
  if (!block.tier_override && block.render_tier === 'L2') return true
  return false
}

export function blocksToOverrides(
  overrides: Iterable<{
    source_type: RuntimeSourceType
    source_id: string
    mode: 'include' | 'exclude' | 'order'
    position: number
    enabled: boolean
    note?: string | null
    tier_override?: RuntimeTierOverride | null
  }>,
): RuntimeContextOverridePayload[] {
  return Array.from(overrides).map((item) => ({
    source_type: item.source_type,
    source_id: item.source_id,
    mode: item.mode,
    position: item.position,
    enabled: item.enabled,
    note: item.note ?? null,
    tier_override: item.tier_override ?? null,
  }))
}

export function isLibraryDragId(id: string): boolean {
  return typeof id === 'string' && id.startsWith('library:')
}

export function isRenderedDragId(id: string): boolean {
  return typeof id === 'string' && id.startsWith('rendered:')
}

export function parseDragId(id: string): {
  kind: 'library' | 'rendered'
  sourceType: RuntimeSourceType
  sourceId: string
} | null {
  const parts = id.split(':')
  if (parts.length < 3) return null
  const [kind, sourceType, ...rest] = parts
  if (kind !== 'library' && kind !== 'rendered') return null
  if (sourceType !== 'prompt' && sourceType !== 'memory') return null
  return { kind, sourceType, sourceId: rest.join(':') }
}
