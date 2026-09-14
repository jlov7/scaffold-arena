import { useEffect, useRef, type RefObject } from 'react'

import { trackEvent } from '../../telemetry/tracker'
import type { RunDeltaSummary } from '../workspaces/ResultsWorkspace'
import type { RunResults } from '../../types'

const CACHE_STORAGE_KEY = 'scaffold_arena_result_cache'

function readResultCache(): Record<string, unknown> {
  try {
    const parsed = JSON.parse(localStorage.getItem(CACHE_STORAGE_KEY) ?? '{}')
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeResultCache(cache: Record<string, unknown>) {
  try {
    localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache))
  } catch {
    // localStorage unavailable
  }
}

interface UseRunCompletionOptions {
  finalResults: RunResults | null
  winnerId: string | null
  runId: string | null
  runMode: 'scaffold' | 'model'
  scaffoldNames: Record<string, string>
  prefersReducedMotion: boolean
  lastRunRef: RefObject<{ taskId: string; modelId: string }>
  buildCacheKey: (taskId: string, modelId: string) => string
  refreshRunHistory: () => Promise<void>
  refreshLeaderboardStats: () => Promise<void>
  setRunDeltaSummary: (summary: RunDeltaSummary | null) => void
}

export function useRunCompletion({
  finalResults,
  winnerId,
  runId,
  runMode,
  scaffoldNames,
  prefersReducedMotion,
  lastRunRef,
  buildCacheKey,
  refreshRunHistory,
  refreshLeaderboardStats,
  setRunDeltaSummary,
}: UseRunCompletionOptions) {
  const lastTrackedRunCompleteRef = useRef<string | null>(null)
  const previousRunSnapshotRef = useRef<{ runId: string | null; winnerId: string | null; results: RunResults | null }>({
    runId: null,
    winnerId: null,
    results: null,
  })

  useEffect(() => {
    if (!finalResults) return
    const previous = previousRunSnapshotRef.current
    if (previous.results && (previous.runId !== runId || previous.results !== finalResults)) {
      const scoreDeltas = Object.keys(finalResults)
        .map((scaffoldId) => ({
          scaffoldId,
          delta: (finalResults[scaffoldId]?.evaluation?.total_score ?? 0) -
            (previous.results?.[scaffoldId]?.evaluation?.total_score ?? 0),
        }))
        .sort((a, b) => Math.abs(b.delta) - Math.abs(a.delta))
      const currentCost = Object.values(finalResults).reduce((sum, result) => sum + (result.metrics?.cost_usd ?? 0), 0)
      const previousCost = Object.values(previous.results).reduce((sum, result) => sum + (result.metrics?.cost_usd ?? 0), 0)
      setRunDeltaSummary({
        previousWinnerId: previous.winnerId,
        currentWinnerId: winnerId,
        winnerChanged: previous.winnerId !== winnerId,
        totalCostDeltaUsd: currentCost - previousCost,
        scoreDeltas,
      })
    } else if (!previous.results) {
      setRunDeltaSummary(null)
    }
    previousRunSnapshotRef.current = { runId, winnerId, results: finalResults }
    if (runId && lastTrackedRunCompleteRef.current !== runId) {
      lastTrackedRunCompleteRef.current = runId
      trackEvent('run_completed', { run_id: runId, winner_id: winnerId })
    }
    if (runId) {
      const params = new URLSearchParams(window.location.search)
      params.set('run_id', runId)
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    }
    if (runMode === 'scaffold') {
      const key = buildCacheKey(lastRunRef.current.taskId, lastRunRef.current.modelId)
      const cache = readResultCache()
      cache[key] = { ts: Date.now(), results: finalResults, winnerId }
      writeResultCache(cache)
    }
    void refreshRunHistory()
    void refreshLeaderboardStats()
    if (!document.hidden) return
    const winnerLabel = winnerId ? scaffoldNames[winnerId] ?? winnerId : 'No winner'
    const winnerScore = winnerId ? finalResults[winnerId]?.evaluation?.total_score?.toFixed(1) ?? 'N/A' : 'N/A'
    if ('Notification' in window && Notification.permission === 'granted') {
      new Notification('Scaffold Arena run complete', { body: `${winnerLabel} won with score ${winnerScore}` })
    }
    const originalTitle = document.title
    if (prefersReducedMotion) {
      document.title = 'Run complete'
      window.setTimeout(() => { document.title = originalTitle }, 2000)
      return
    }
    let tick = 0
    const timer = window.setInterval(() => {
      document.title = tick % 2 === 0 ? 'Run complete' : originalTitle
      tick += 1
      if (tick > 6 || !document.hidden) {
        window.clearInterval(timer)
        document.title = originalTitle
      }
    }, 700)
  }, [buildCacheKey, finalResults, lastRunRef, prefersReducedMotion, refreshLeaderboardStats, refreshRunHistory, runId, runMode, scaffoldNames, setRunDeltaSummary, winnerId])
}
