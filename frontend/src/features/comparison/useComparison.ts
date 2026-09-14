import { useCallback, useState, type RefObject } from 'react'

import { createComparison } from '../../api/client'
import { useSSE } from '../../hooks/useSSE'
import { trackEvent } from '../../telemetry/tracker'
import type { RunMetrics } from '../../types'

export interface ComparisonCaseDisplay {
  case_id: string
  label: string
  model_id: string
  scaffold_id: string
  score: number
  cost: number
  metrics?: RunMetrics
}

const CASE_ORDER = [
  'cheap_winning',
  'expensive_bare',
  'expensive_winning',
  'model_a',
  'model_b',
]

function caseLabel(caseId: string): string {
  switch (caseId) {
    case 'cheap_winning': return 'Cheap Model + Winner'
    case 'expensive_bare': return 'Expensive + Bare'
    case 'expensive_winning': return 'Expensive + Winner'
    case 'model_a': return 'Model A'
    case 'model_b': return 'Model B'
    default: return caseId
  }
}

interface UseComparisonOptions {
  lastRunRef: RefObject<{ taskId: string; modelId: string }>
  getErrorMessage: (error: unknown) => string
  pushToast: (type: 'error' | 'success' | 'info', message: string) => void
  setOperationError: (message: string | null) => void
  refreshRunHistory: () => Promise<void>
  refreshLeaderboardStats: () => Promise<void>
}

export function useComparison({
  lastRunRef,
  getErrorMessage,
  pushToast,
  setOperationError,
  refreshRunHistory,
  refreshLeaderboardStats,
}: UseComparisonOptions) {
  const [comparisonStreamUrl, setComparisonStreamUrl] = useState<string | null>(null)
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonCases, setComparisonCases] = useState<ComparisonCaseDisplay[]>([])

  const handleComparisonEvent = useCallback((eventName: string, data: unknown) => {
    const payload = data as Record<string, unknown>
    if (eventName === 'comparison_started') {
      setComparisonLoading(true)
      return
    }
    if (eventName !== 'comparison_complete') return

    const results = payload.results as Record<string, Record<string, unknown>>
    const comparisonRunId = typeof payload.run_id === 'string' && payload.run_id.length > 0
      ? payload.run_id
      : null
    const cases = CASE_ORDER.filter((caseId) => caseId in results).map((caseId) => {
      const result = results[caseId]
      const metrics = result.metrics as RunMetrics | undefined
      const evaluation = result.evaluation as Record<string, unknown> | undefined
      return {
        case_id: caseId,
        label: caseLabel(caseId),
        model_id: result.model_id as string,
        scaffold_id: result.scaffold_id as string,
        score: (evaluation?.total_score as number) ?? 0,
        cost: metrics?.cost_usd ?? 0,
        metrics,
      }
    })
    setComparisonCases(cases)
    setComparisonLoading(false)
    setComparisonStreamUrl(null)
    trackEvent('comparison_completed', { run_id: comparisonRunId, cases: cases.length })
    if (comparisonRunId) {
      const params = new URLSearchParams(window.location.search)
      params.set('run_id', comparisonRunId)
      window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    }
    void refreshRunHistory()
    void refreshLeaderboardStats()
  }, [refreshLeaderboardStats, refreshRunHistory])

  useSSE(comparisonStreamUrl, handleComparisonEvent, {
    onFailed: () => {
      setComparisonLoading(false)
      setComparisonStreamUrl(null)
      const message = 'Comparison stream connection failed.'
      setOperationError(message)
      pushToast('error', message)
    },
  })

  const runComparison = useCallback(async (winningScaffoldId: string) => {
    const { taskId, modelId } = lastRunRef.current
    if (!taskId) return
    setComparisonCases([])
    setComparisonLoading(true)
    setOperationError(null)
    trackEvent('comparison_started', {
      task_id: taskId,
      model_id: modelId,
      winning_scaffold_id: winningScaffoldId,
    })
    try {
      const result = await createComparison({
        task_id: taskId,
        expensive_model_id: modelId,
        cheap_model_id: 'claude-haiku-4-5',
        winning_scaffold_id: winningScaffoldId,
      })
      setComparisonStreamUrl(result.stream_url)
    } catch (error) {
      setComparisonLoading(false)
      const message = `Failed to run comparison: ${getErrorMessage(error)}`
      setOperationError(message)
      pushToast('error', message)
    }
  }, [getErrorMessage, lastRunRef, pushToast, setOperationError])

  const resetComparison = useCallback(() => {
    setComparisonCases([])
    setComparisonLoading(false)
    setComparisonStreamUrl(null)
  }, [])

  const beginComparisonStream = useCallback((streamUrl: string) => {
    setComparisonLoading(true)
    setComparisonStreamUrl(streamUrl)
  }, [])

  const startComparison = useCallback(() => setComparisonLoading(true), [])

  return {
    beginComparisonStream,
    comparisonCases,
    comparisonLoading,
    resetComparison,
    runComparison,
    startComparison,
  }
}
