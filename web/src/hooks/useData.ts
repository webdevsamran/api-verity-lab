import { useEffect, useState } from 'react'
import { loadData, type DemoData } from '../data'

/** Load the demo artifact bundle once per session. */
export function useData(): { data: DemoData | null; error: string | null } {
  const [data, setData] = useState<DemoData | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    loadData().then(setData).catch((e) => setError(String(e)))
  }, [])
  return { data, error }
}
