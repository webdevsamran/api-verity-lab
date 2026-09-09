import { useCallback, useEffect, useState } from 'react'
import { loadData, resetDataCache, type DemoData } from '../data'

export interface DataState {
  data: DemoData | null
  error: string | null
  loading: boolean
  /** Drop the cached artifact and fetch again. */
  retry: () => void
}

/**
 * Load the result artifact once per session.
 *
 * `retry` exists because the failure is recoverable and the reader is the one
 * who knows it: the app is often served from a file:// path or a half-started
 * dev server, and a banner reading "failed to load" with no way to try again
 * makes a transient error look permanent. `loadData` already declines to cache
 * a rejected promise, so a retry genuinely re-fetches.
 */
export function useData(): DataState {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)
    loadData()
      .then((next) => {
        if (!cancelled) setData(next)
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e))
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [attempt])

  const retry = useCallback(() => {
    resetDataCache()
    setAttempt((n) => n + 1)
  }, [])

  return { data, error, loading, retry }
}
