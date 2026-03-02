import type { ScreenerResults } from '../types/screener'

const RESULTS_URL = import.meta.env.VITE_RESULTS_URL as string | undefined
const CACHE_KEY = 'screener_results_cache'
const CACHE_TTL_MS = 4 * 60 * 60 * 1000 // 4 hours

interface CacheEntry {
  data: ScreenerResults
  timestamp: number
}

function readCache(): ScreenerResults | null {
  try {
    const raw = localStorage.getItem(CACHE_KEY)
    if (!raw) return null
    const entry: CacheEntry = JSON.parse(raw)
    if (Date.now() - entry.timestamp > CACHE_TTL_MS) {
      localStorage.removeItem(CACHE_KEY)
      return null
    }
    return entry.data
  } catch {
    return null
  }
}

function writeCache(data: ScreenerResults): void {
  try {
    const entry: CacheEntry = { data, timestamp: Date.now() }
    localStorage.setItem(CACHE_KEY, JSON.stringify(entry))
  } catch {
    // Storage may be full — silently ignore
  }
}

export async function fetchScreenerResults(): Promise<ScreenerResults | null> {
  const cached = readCache()
  if (cached) return cached

  const url = RESULTS_URL ?? '/results/latest.json'
  const resp = await fetch(url, { cache: 'no-cache' })

  if (resp.status === 404) return null

  if (!resp.ok) throw new Error(`Failed to fetch results (${resp.status})`)

  const contentType = resp.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    // Server returned HTML (e.g. SPA fallback) instead of JSON
    return null
  }

  const data: ScreenerResults = await resp.json()
  writeCache(data)
  return data
}
