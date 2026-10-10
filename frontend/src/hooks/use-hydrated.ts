import { useSyncExternalStore } from 'react'

const subscribe = () => () => {}

/**
 * False while React hydrates server HTML, true afterwards.
 *
 * A component that hydrates after a sibling has already filled a shared query
 * cache would otherwise render that data against server HTML that never had it.
 */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    subscribe,
    () => true,
    () => false,
  )
}
