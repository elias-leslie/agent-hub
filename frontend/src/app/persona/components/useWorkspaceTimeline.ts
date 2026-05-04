'use client'

import { useVirtualizer } from '@tanstack/react-virtual'
import { useMemo } from 'react'
import type { FilterMode } from './pulse-helpers'
import { canAnchorChildRuns, isChildRunItem } from './workspace-feed'
import { isRoutineHeartbeatBlock } from './workspace-live-events'
import type {
  FeedHeartbeat,
  FeedItem,
  ItemTimelineBlock,
  TimelineBlock,
  TimelineRow,
} from './workspace-types'
import { formatDayLabel } from './workspace-utils'

interface UseWorkspaceTimelineOptions {
  mergedItems: FeedItem[]
  deferredSearch: string
  filterMode: FilterMode
  firstUnreadItemId: string | null
  expandedEntryIds: Record<string, boolean>
  expandedRoutineGroupIds: Record<string, boolean>
  scrollRef: React.RefObject<HTMLDivElement | null>
}

function groupItemsByDay(
  items: FeedItem[],
  deferredSearch: string,
  filterMode: FilterMode,
): Array<{ label: string; blocks: TimelineBlock[] }> {
  const groups: Array<{ label: string; blocks: TimelineBlock[] }> = []
  let currentLabel = ''

  for (const item of items) {
    const label = formatDayLabel(item.timestamp)
    if (label !== currentLabel) {
      currentLabel = label
      groups.push({ label, blocks: [] })
    }
    const currentBlocks = groups[groups.length - 1].blocks
    if (isChildRunItem(item) && item.entry.parent_session_id) {
      const parentBlockIndex = currentBlocks.findLastIndex(
        (block) =>
          block.kind === 'item' &&
          canAnchorChildRuns(block.anchorItem) &&
          block.anchorItem.sessionId === item.entry.parent_session_id,
      )
      if (parentBlockIndex >= 0) {
        const parentBlock = currentBlocks[parentBlockIndex]
        if (parentBlock.kind === 'item') {
          parentBlock.childRuns.push(item)
        }
        continue
      }
    }
    currentBlocks.push({ kind: 'item', anchorItem: item, childRuns: [] })
  }

  return groups.map((group) => ({
    ...group,
    blocks: compressRoutineBlocks(group.blocks, deferredSearch, filterMode),
  }))
}

function compressRoutineBlocks(
  blocks: TimelineBlock[],
  deferredSearch: string,
  filterMode: FilterMode,
): TimelineBlock[] {
  const compressedBlocks: TimelineBlock[] = []
  let pendingRoutine: ItemTimelineBlock[] = []

  const flushRoutine = () => {
    if (pendingRoutine.length === 0) return
    if (pendingRoutine.length === 1) {
      compressedBlocks.push(pendingRoutine[0])
    } else {
      compressedBlocks.push({
        kind: 'routine_group',
        id: `routine:${pendingRoutine[0].anchorItem.id}:${pendingRoutine.at(-1)?.anchorItem.id}`,
        items: pendingRoutine.map((block) => ({
          anchorItem: block.anchorItem as FeedHeartbeat,
          childRuns: block.childRuns,
        })),
      })
    }
    pendingRoutine = []
  }

  for (const block of blocks) {
    if (block.kind !== 'item') {
      flushRoutine()
      compressedBlocks.push(block)
      continue
    }
    if (isRoutineHeartbeatBlock(block, !!deferredSearch.trim(), filterMode)) {
      pendingRoutine.push(block)
      continue
    }
    flushRoutine()
    compressedBlocks.push(block)
  }
  flushRoutine()
  return compressedBlocks
}

function buildTimelineRows(
  groupedItems: Array<{ label: string; blocks: TimelineBlock[] }>,
  firstUnreadItemId: string | null,
): TimelineRow[] {
  const rows: TimelineRow[] = []
  for (const group of groupedItems) {
    rows.push({
      kind: 'divider',
      id: `divider:${group.label}`,
      label: group.label,
    })
    for (const block of group.blocks) {
      if (block.kind === 'routine_group') {
        const containsUnread = Boolean(
          firstUnreadItemId &&
            block.items.some(
              ({ anchorItem, childRuns }) =>
                anchorItem.id === firstUnreadItemId ||
                childRuns.some((cr) => cr.id === firstUnreadItemId),
            ),
        )
        if (containsUnread)
          rows.push({ kind: 'unread', id: `unread:${block.id}` })
        rows.push({ kind: 'routine_group', id: block.id, block })
        continue
      }
      if (
        firstUnreadItemId &&
        (block.anchorItem.id === firstUnreadItemId ||
          block.childRuns.some((cr) => cr.id === firstUnreadItemId))
      ) {
        rows.push({ kind: 'unread', id: `unread:${block.anchorItem.id}` })
      }
      rows.push({
        kind: 'item',
        id: `item:${block.anchorItem.id}`,
        item: block.anchorItem,
        childRuns: block.childRuns,
      })
    }
  }
  return rows
}

function buildIndexMap<K>(
  timelineRows: TimelineRow[],
  getKeys: (row: TimelineRow, index: number) => K[],
): Map<K, number> {
  const indexMap = new Map<K, number>()
  timelineRows.forEach((row, index) => {
    for (const key of getKeys(row, index)) {
      indexMap.set(key, index)
    }
  })
  return indexMap
}

function getStreamItemIds(row: TimelineRow): string[] {
  if (row.kind === 'item') {
    return [row.item.id, ...row.childRuns.map((cr) => cr.id)]
  }
  if (row.kind === 'routine_group') {
    return row.block.items.flatMap(({ anchorItem, childRuns }) => [
      anchorItem.id,
      ...childRuns.map((cr) => cr.id),
    ])
  }
  return []
}

function getSessionIds(row: TimelineRow): string[] {
  if (row.kind === 'item') {
    const ids: string[] = []
    if (row.item.sessionId) ids.push(row.item.sessionId)
    row.childRuns.forEach((cr) => ids.push(cr.sessionId))
    return ids
  }
  if (row.kind === 'routine_group') {
    return row.block.items.flatMap(({ anchorItem, childRuns }) => [
      anchorItem.sessionId,
      ...childRuns.map((cr) => cr.sessionId),
    ])
  }
  return []
}

export function useWorkspaceTimeline({
  mergedItems,
  deferredSearch,
  filterMode,
  firstUnreadItemId,
  expandedEntryIds,
  expandedRoutineGroupIds,
  scrollRef,
}: UseWorkspaceTimelineOptions) {
  const groupedItems = useMemo(
    () => groupItemsByDay(mergedItems, deferredSearch, filterMode),
    [mergedItems, deferredSearch, filterMode],
  )

  const timelineRows = useMemo(
    () => buildTimelineRows(groupedItems, firstUnreadItemId),
    [groupedItems, firstUnreadItemId],
  )

  const rowIndexByStreamItemId = useMemo(
    () => buildIndexMap(timelineRows, getStreamItemIds),
    [timelineRows],
  )

  const rowIndexBySessionId = useMemo(
    () => buildIndexMap(timelineRows, getSessionIds),
    [timelineRows],
  )

  const virtualizer = useVirtualizer({
    count: timelineRows.length,
    getScrollElement: () => scrollRef.current,
    estimateSize: (index) => {
      const row = timelineRows[index]
      if (!row) return 80
      if (row.kind === 'divider') return 56
      if (row.kind === 'unread') return 40
      if (row.kind === 'routine_group')
        return expandedRoutineGroupIds[row.block.id] ? 360 : 120
      const expanded =
        row.item.kind !== 'message' && expandedEntryIds[row.item.id]
      const childRunCount = row.childRuns.length
      return expanded ? 420 + childRunCount * 140 : 160 + childRunCount * 140
    },
    overscan: 10,
  })

  const hasExpandedTimelineContent = useMemo(
    () =>
      Object.values(expandedEntryIds).some(Boolean) ||
      Object.values(expandedRoutineGroupIds).some(Boolean),
    [expandedEntryIds, expandedRoutineGroupIds],
  )

  return {
    groupedItems,
    timelineRows,
    rowIndexByStreamItemId,
    rowIndexBySessionId,
    virtualizer,
    hasExpandedTimelineContent,
  }
}
