import { describe, expect, it } from 'vitest'
import {
  blockKey,
  excludeBlock,
  parseDragId,
  pinBlock,
  reorderBlocks,
  restoreBlock,
  setRenderMode,
  unpinBlock,
} from '@/components/runtime-context/resolver'
import type {
  RuntimeContextBlock,
  RuntimeContextOverridePayload,
} from '@/lib/api/runtime-context'

function memoryBlock(id: string, position = 1000): RuntimeContextBlock {
  return {
    id: `memory:${id}`,
    source_type: 'memory',
    source_id: id,
    title: `mem ${id}`,
    content: 'memory content',
    token_count: 10,
    origin: 'auto',
    source: 'auto',
    auto_reason: 'tier:reference',
    mode: 'order',
    position,
    tier: 'reference',
    render_tier: null,
    render_mode: null,
    tier_override: null,
    scope: 'global',
    scope_id: null,
    tags: [],
  }
}

function promptBlock(slug: string, position = 100): RuntimeContextBlock {
  return {
    id: `prompt:${slug}`,
    source_type: 'prompt',
    source_id: slug,
    title: `prompt ${slug}`,
    content: 'prompt content',
    token_count: 20,
    origin: 'auto',
    source: 'auto',
    auto_reason: 'boot_eligible',
    mode: 'order',
    position,
    tier: null,
    render_tier: null,
    render_mode: null,
    tier_override: null,
    scope: 'global',
    scope_id: null,
    tags: [],
  }
}

function override(
  type: 'memory' | 'prompt',
  id: string,
  partial: Partial<RuntimeContextOverridePayload> = {},
): RuntimeContextOverridePayload {
  return {
    source_type: type,
    source_id: id,
    mode: 'order',
    position: 100,
    enabled: true,
    note: null,
    tier_override: null,
    ...partial,
  }
}

describe('runtime-context resolver', () => {
  it('pinBlock adds an include override at the next position', () => {
    const next = pinBlock([], [memoryBlock('a', 50)], 'memory', 'b')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({
      source_type: 'memory',
      source_id: 'b',
      mode: 'include',
    })
    expect(next[0].position).toBeGreaterThan(50)
  })

  it('pinBlock respects an explicit insert position', () => {
    const next = pinBlock([], [], 'prompt', 'reviewer', 25)
    expect(next[0]).toMatchObject({ position: 25, mode: 'include' })
  })

  it('unpinBlock removes the matching override', () => {
    const next = unpinBlock(
      [override('memory', 'a'), override('prompt', 'p')],
      'memory',
      'a',
    )
    expect(next).toHaveLength(1)
    expect(next[0].source_id).toBe('p')
  })

  it('excludeBlock flips the override mode to exclude', () => {
    const block = memoryBlock('a', 1000)
    const next = excludeBlock([], [block], block)
    expect(next[0]).toMatchObject({
      source_type: 'memory',
      source_id: 'a',
      mode: 'exclude',
      position: 1000,
    })
  })

  it('restoreBlock drops a pure exclude override', () => {
    const block = memoryBlock('a')
    const after = restoreBlock(
      [override('memory', 'a', { mode: 'exclude' })],
      block,
    )
    expect(after).toHaveLength(0)
  })

  it('restoreBlock keeps tier_override when restoring', () => {
    const block = memoryBlock('a')
    const after = restoreBlock(
      [override('memory', 'a', { mode: 'exclude', tier_override: 'L1' })],
      block,
    )
    expect(after).toHaveLength(1)
    expect(after[0]).toMatchObject({ mode: 'order', tier_override: 'L1' })
  })

  it('reorderBlocks rewrites positions based on new index order', () => {
    const blocks = [memoryBlock('a'), memoryBlock('b'), memoryBlock('c')]
    const reversed = [blocks[2], blocks[1], blocks[0]]
    const overrides = reorderBlocks([], reversed)
    expect(overrides.map((o) => o.source_id)).toEqual(['c', 'b', 'a'])
    expect(overrides.map((o) => o.position)).toEqual([10, 20, 30])
  })

  it('reorderBlocks preserves overrides for blocks not in the ordered list', () => {
    const overrides = [
      override('memory', 'unrelated', { position: 999, mode: 'exclude' }),
    ]
    const next = reorderBlocks(overrides, [memoryBlock('a')])
    expect(next).toHaveLength(2)
    expect(next.find((o) => o.source_id === 'unrelated')?.mode).toBe('exclude')
  })

  it('reorderBlocks keeps mode=exclude on excluded rows in the ordered list', () => {
    // Excluded rows are part of the visible ordered list now, so reordering
    // must keep them excluded (and stamp them with a fresh in-place position)
    // instead of demoting them back to mode=order.
    const overrides = [
      override('memory', 'b', { position: 1500, mode: 'exclude' }),
    ]
    const next = reorderBlocks(overrides, [
      memoryBlock('a', 1000),
      memoryBlock('b', 1500),
      memoryBlock('c', 2000),
    ])
    expect(next.map((o) => o.source_id)).toEqual(['a', 'b', 'c'])
    expect(next.map((o) => o.position)).toEqual([10, 20, 30])
    expect(next.find((o) => o.source_id === 'b')?.mode).toBe('exclude')
    expect(next.find((o) => o.source_id === 'a')?.mode).toBe('order')
  })

  it('setRenderMode("auto") drops a row that has no other override reason', () => {
    const block = memoryBlock('a')
    const overrides = [override('memory', 'a', { tier_override: 'L0' })]
    const next = setRenderMode(overrides, block, 'auto')
    expect(next).toHaveLength(0)
  })

  it('setRenderMode("compact") sets tier_override L1', () => {
    const block = memoryBlock('a')
    const next = setRenderMode([], block, 'compact')
    expect(next[0]).toMatchObject({ tier_override: 'L1', mode: 'order' })
  })

  it('setRenderMode keeps an existing exclude row even when tier becomes auto', () => {
    const block = memoryBlock('a')
    const overrides = [
      override('memory', 'a', { mode: 'exclude', tier_override: 'L1' }),
    ]
    const next = setRenderMode(overrides, block, 'auto')
    expect(next).toHaveLength(1)
    expect(next[0]).toMatchObject({ mode: 'exclude', tier_override: null })
  })

  it('blockKey is stable across calls', () => {
    expect(blockKey(memoryBlock('uuid-1'))).toBe('memory:uuid-1')
    expect(blockKey(promptBlock('slug-1'))).toBe('prompt:slug-1')
  })

  it('parseDragId parses library + rendered ids', () => {
    expect(parseDragId('library:memory:abc-123')).toEqual({
      kind: 'library',
      sourceType: 'memory',
      sourceId: 'abc-123',
    })
    expect(parseDragId('rendered:prompt:reviewer')).toEqual({
      kind: 'rendered',
      sourceType: 'prompt',
      sourceId: 'reviewer',
    })
    expect(parseDragId('garbage')).toBeNull()
  })
})
