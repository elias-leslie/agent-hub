import { type RefObject, useEffect } from 'react'

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  if (target.isContentEditable) return true
  const tag = target.tagName
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT'
}

function focusRow(listRef: RefObject<HTMLElement | null>, id: string) {
  const row = listRef.current?.querySelector<HTMLElement>(
    `[data-session-id="${CSS.escape(id)}"]`,
  )
  row?.focus({ preventScroll: false })
  row?.scrollIntoView({ block: 'nearest' })
}

interface UseSessionKeyboardProps {
  ids: readonly string[]
  /** Row the keyboard acts on; the expanded session when one is open. */
  activeId: string | null
  expanded: boolean
  listRef: RefObject<HTMLElement | null>
  searchRef: RefObject<HTMLInputElement | null>
  onActivate: (id: string) => void
  onToggle: (id: string) => void
  onCollapse: () => void
}

/**
 * Selection follows session ids, so a refetch that reorders rows never moves
 * the cursor to a different session. Shortcuts are ignored inside form fields.
 */
export function useSessionKeyboard({
  ids,
  activeId,
  expanded,
  listRef,
  searchRef,
  onActivate,
  onToggle,
  onCollapse,
}: UseSessionKeyboardProps) {
  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if (event.metaKey || event.ctrlKey || event.altKey) return

      if (isEditableTarget(event.target)) {
        if (event.key === 'Escape' && event.target === searchRef.current) {
          searchRef.current?.blur()
          if (activeId) focusRow(listRef, activeId)
        }
        return
      }

      if (event.key === '/') {
        event.preventDefault()
        // Inside an expanded session, / searches that session's log.
        const panel = (event.target as HTMLElement | null)?.closest?.(
          '[data-testid="session-inline"]',
        )
        const local = panel?.querySelector<HTMLInputElement>(
          'input[data-session-search]',
        )
        if (local && local.offsetParent !== null) local.focus()
        else searchRef.current?.focus()
        return
      }

      if (event.key === 'Escape' && expanded) {
        event.preventDefault()
        const id = activeId
        onCollapse()
        if (id) requestAnimationFrame(() => focusRow(listRef, id))
        return
      }

      // Only list navigation keys beyond this point; leave buttons, links and
      // the expanded session's own controls alone.
      const target = event.target as HTMLElement | null
      const onRow = Boolean(target?.dataset.sessionId)
      const onBody = target === document.body || target === null
      if (!onRow && !onBody) return
      if (ids.length === 0) return

      const index = activeId ? ids.indexOf(activeId) : -1
      const move = (delta: number) => {
        event.preventDefault()
        const nextIndex =
          index === -1
            ? 0
            : Math.min(Math.max(index + delta, 0), ids.length - 1)
        const nextId = ids[nextIndex]
        onActivate(nextId)
        focusRow(listRef, nextId)
      }

      switch (event.key) {
        case 'j':
        case 'ArrowDown':
          move(1)
          break
        case 'k':
        case 'ArrowUp':
          move(-1)
          break
        case 'Enter':
        case ' ':
          if (activeId) {
            event.preventDefault()
            onToggle(activeId)
          }
          break
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [
    activeId,
    ids,
    listRef,
    expanded,
    onActivate,
    onCollapse,
    onToggle,
    searchRef,
  ])
}
