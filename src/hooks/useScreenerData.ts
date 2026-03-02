import { useEffect, useState } from 'react'
import { fetchScreenerResults } from '../services/screenerService'
import type { ScreenerResults } from '../types/screener'

interface ScreenerState {
  data: ScreenerResults | null
  isLoading: boolean
  error: string | null
  noData: boolean
  refetch: () => void
}

export function useScreenerData(): ScreenerState {
  const [data, setData] = useState<ScreenerResults | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [noData, setNoData] = useState(false)
  const [tick, setTick] = useState(0)

  useEffect(() => {
    let cancelled = false
    setIsLoading(true)
    setError(null)
    setNoData(false)

    fetchScreenerResults()
      .then((results) => {
        if (!cancelled) {
          if (results === null) {
            setNoData(true)
          } else {
            setData(results)
          }
          setIsLoading(false)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : 'Failed to load data')
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [tick])

  return {
    data,
    isLoading,
    error,
    noData,
    refetch: () => setTick((t) => t + 1),
  }
}
