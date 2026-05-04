import { useCallback, useEffect, useRef } from 'react'

interface UseDebouncedAutosaveOptions<TResult, TPayload> {
  delayMs?: number
  save: (payload: TPayload) => Promise<TResult>
  onSuccess: (result: TResult) => void
  onError: (error: unknown) => void
}

export function useDebouncedAutosave<TResult, TPayload>({
  delayMs = 500,
  save,
  onSuccess,
  onError,
}: UseDebouncedAutosaveOptions<TResult, TPayload>) {
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const mountedRef = useRef(true)
  const requestIdRef = useRef(0)

  useEffect(() => {
    return () => {
      mountedRef.current = false
      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }
    }
  }, [])

  return useCallback(
    (payload: TPayload) => {
      requestIdRef.current += 1
      const requestId = requestIdRef.current

      if (timerRef.current) {
        clearTimeout(timerRef.current)
      }

      timerRef.current = setTimeout(async () => {
        try {
          const result = await save(payload)
          if (!mountedRef.current || requestId !== requestIdRef.current) {
            return
          }
          onSuccess(result)
        } catch (error) {
          if (!mountedRef.current || requestId !== requestIdRef.current) {
            return
          }
          onError(error)
        }
      }, delayMs)
    },
    [delayMs, onError, onSuccess, save],
  )
}
