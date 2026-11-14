import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Load data from the API, optionally polling. `deps` re-trigger the load.
 * Polling pauses while the tab is hidden.
 */
export function useApi<T>(loader: () => Promise<T>, deps: unknown[] = [], pollMs?: number) {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const loaderRef = useRef(loader)
  loaderRef.current = loader

  const reload = useCallback(async () => {
    try {
      const d = await loaderRef.current()
      setData(d)
      setError(null)
    } catch (e) {
      setError(e as Error)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setLoading(true)
    void reload()
    if (!pollMs) return
    const t = setInterval(() => { if (!document.hidden) void reload() }, pollMs)
    return () => clearInterval(t)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, pollMs])

  return { data, error, loading, reload, setData }
}
