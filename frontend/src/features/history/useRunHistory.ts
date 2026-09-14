import { useCallback, useEffect, useState, type RefObject } from 'react'

import { fetchRunDetails, fetchRunDiagnostics, fetchRuns, fetchStats } from '../../api/client'
import { parseRunDetailsResponse, parseRunListResponse, type ParsedRunRecord } from '../../lib/schema'
import type { AppView } from '../../app/viewState'
import type { LeaderboardStats, RunResults, RunTimelineEvent } from '../../types'

export type RunHistoryRecord = ParsedRunRecord

interface UseRunHistoryOptions {
  metaReady: boolean
  navigateToView: (view: AppView) => void
  hydrateFromResults: (results: RunResults, winnerId: string | null, options: { cached: boolean }) => void
  setTimelineEvents: (events: RunTimelineEvent[]) => void
  setSelectedTaskId: (taskId: string) => void
  setSelectedModelId: (modelId: string) => void
  setHasEverRun: (hasEverRun: boolean) => void
  selectedTaskId: string
  selectedModelId: string
  lastRunRef: RefObject<{ taskId: string; modelId: string }>
  getErrorMessage: (error: unknown) => string
  pushToast: (type: 'error' | 'success' | 'info', message: string) => void
}

export function useRunHistory({
  metaReady,
  navigateToView,
  hydrateFromResults,
  setTimelineEvents,
  setSelectedTaskId,
  setSelectedModelId,
  setHasEverRun,
  selectedTaskId,
  selectedModelId,
  lastRunRef,
  getErrorMessage,
  pushToast,
}: UseRunHistoryOptions) {
  const [runHistory, setRunHistory] = useState<RunHistoryRecord[]>([])
  const [historyHydrationPending, setHistoryHydrationPending] = useState(false)
  const [leaderboardStats, setLeaderboardStats] = useState<LeaderboardStats | null>(null)

  const refreshRunHistory = useCallback(async () => {
    try {
      const runs = parseRunListResponse(await fetchRuns(100)).runs.slice()
      runs.sort((a, b) => Number(b.completed_at ?? b.created_at ?? 0) - Number(a.completed_at ?? a.created_at ?? 0))
      setRunHistory(runs)
    } catch (error) {
      pushToast('error', `Failed to load run history: ${getErrorMessage(error)}`)
    }
  }, [getErrorMessage, pushToast])

  const refreshLeaderboardStats = useCallback(async () => {
    try {
      setLeaderboardStats(await fetchStats(2000))
    } catch {
      setLeaderboardStats(null)
    }
  }, [])

  const loadRunFromHistory = useCallback(async (historyRunId: string) => {
    setHistoryHydrationPending(true)
    navigateToView('results')
    try {
      const record = parseRunDetailsResponse(await fetchRunDetails(historyRunId))
      const results = (record.results ?? {}) as RunResults
      const hydratedWinner = (record.winner_id as string | null) ?? null
      const diagnostics = await fetchRunDiagnostics(historyRunId).catch(() => null)
      if (diagnostics && Array.isArray((diagnostics as { timeline?: unknown }).timeline)) {
        setTimelineEvents(((diagnostics as { timeline: RunTimelineEvent[] }).timeline ?? []).slice(-400))
      } else {
        setTimelineEvents([])
      }
      hydrateFromResults(results, hydratedWinner, { cached: false })
      setHasEverRun(true)
      const taskId = record.task_id ?? ''
      const modelId = record.model_id ?? ''
      lastRunRef.current = { taskId, modelId }
      setSelectedTaskId(taskId || selectedTaskId)
      setSelectedModelId(modelId || selectedModelId)
      const params = new URLSearchParams(window.location.search)
      params.set('run_id', historyRunId)
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
      pushToast('info', `Loaded run ${historyRunId}`)
    } catch (error) {
      pushToast('error', `Failed to load run: ${getErrorMessage(error)}`)
    } finally {
      setHistoryHydrationPending(false)
    }
  }, [getErrorMessage, hydrateFromResults, lastRunRef, navigateToView, pushToast, selectedModelId, selectedTaskId, setHasEverRun, setSelectedModelId, setSelectedTaskId, setTimelineEvents])

  useEffect(() => {
    if (!metaReady) return
    void refreshRunHistory()
    void refreshLeaderboardStats()
  }, [metaReady, refreshLeaderboardStats, refreshRunHistory])

  return {
    historyHydrationPending,
    leaderboardStats,
    loadRunFromHistory,
    refreshLeaderboardStats,
    refreshRunHistory,
    runHistory,
  }
}
