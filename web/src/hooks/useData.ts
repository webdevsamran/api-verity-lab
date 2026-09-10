import { useCallback, useEffect, useState } from 'react'
import { loadData, resetDataCache, type DemoData } from '../data'
import { loadLive, readLiveConfig, writeLiveConfig, type LiveConfig } from '../live'

export interface DataState {
  data: DemoData | null
  error: string | null
  loading: boolean
  /** Drop the cached artifact and fetch again. */
  retry: () => void
  /** The live server this session is pointed at, or null for the artifact. */
  live: LiveConfig | null
  /** Point at a server, or pass null to go back to the static artifact. */
  setLive: (config: LiveConfig | null) => void
}

/**
 * Load the dashboard's data, from a static artifact or a live server.
 *
 * `retry` exists because the failure is recoverable and the reader is the one
 * who knows it: the app is often served from a file:// path or a half-started
 * dev server, and a banner reading "failed to load" with no way to try again
 * makes a transient error look permanent. `loadData` already declines to cache
 * a rejected promise, so a retry genuinely re-fetches.
 *
 * The live path is deliberately not cached. An artifact is a file that does
 * not change while you look at it; a server's state does, and a dashboard
 * showing an approval queue from twenty minutes ago is worse than one that
 * takes a moment to load.
 */
export function useData(): DataState {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [attempt, setAttempt] = useState(0)
  const [live, setLiveState] = useState<LiveConfig | null>(() => readLiveConfig())

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    setError(null)

    const load = live
      ? loadLive(live).then((result) => ({
          ...result.data,
          source: {
            kind: 'live' as const,
            label: live.baseUrl,
            available: result.available as string[],
            failed: result.failed,
          },
        }))
      : loadData().then((next) => ({
          ...next,
          /* Stamped here rather than written into the artifact, so an artifact
           * generated before this existed still says where it came from. */
          source: next.source ?? {
            kind: 'artifact' as const,
            label: next.meta?.label ?? 'demo-data.json',
            available: Object.keys(next).filter((k) => k !== 'meta' && k !== 'source'),
          },
        }))

    load
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
  }, [attempt, live])

  const retry = useCallback(() => {
    resetDataCache()
    setAttempt((n) => n + 1)
  }, [])

  const setLive = useCallback((config: LiveConfig | null) => {
    writeLiveConfig(config)
    resetDataCache()
    setLiveState(config)
  }, [])

  return { data, error, loading, retry, live, setLive }
}
