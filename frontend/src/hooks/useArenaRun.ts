import { useState, useCallback, useRef } from 'react'
import {
  createArenaRun,
  cancelRun,
  fetchRunDetails,
  getEventStreamUrl,
} from '../api/client'
import { useSSE } from './useSSE'
import { parseRunDetailsResponse } from '../lib/schema'
import type {
  PanelState,
  RunResults,
  ScaffoldMeta,
  ScaffoldDeltaEvent,
  ScaffoldPhaseEvent,
  ScaffoldCompletedEvent,
  EvaluationCompletedEvent,
  RunCompleteEvent,
} from '../types'

function initPanel(scaffold: ScaffoldMeta): PanelState {
  return {
    scaffoldId: scaffold.id,
    scaffoldName: scaffold.name,
    status: 'idle',
    phase: '',
    streamedText: '',
    output: '',
    metrics: null,
    evaluation: null,
    error: null,
  }
}

export function useArenaRun(scaffolds: ScaffoldMeta[]) {
  const [panels, setPanels] = useState<PanelState[]>(() =>
    scaffolds.map(initPanel),
  )
  const [runId, setRunId] = useState<string | null>(null)
  const [streamUrl, setStreamUrl] = useState<string | null>(null)
  const [winnerId, setWinnerId] = useState<string | null>(null)
  const [finalResults, setFinalResults] = useState<RunResults | null>(null)
  const [isRunning, setIsRunning] = useState(false)
  const [isCachedResult, setIsCachedResult] = useState(false)
  const [runError, setRunError] = useState<string | null>(null)
  const [connectionState, setConnectionState] = useState<
    'idle' | 'connected' | 'retrying' | 'failed'
  >('idle')
  const [connectionRetryCount, setConnectionRetryCount] = useState(0)
  const startInFlightRef = useRef(false)
  const lastStartRequestRef = useRef<{
    key: string
    startedAtMs: number
  } | null>(null)

  // Use refs for streaming text to avoid re-renders per token
  const textBuffers = useRef<Record<string, string>>({})
  const rafHandle = useRef<number | null>(null)

  const updatePanel = useCallback(
    (scaffoldId: string, update: Partial<PanelState>) => {
      setPanels((prev) =>
        prev.map((p) =>
          p.scaffoldId === scaffoldId ? { ...p, ...update } : p,
        ),
      )
    },
    [],
  )

  // Flush buffered text to state via requestAnimationFrame
  const scheduleFlush = useCallback(() => {
    if (rafHandle.current !== null) return
    rafHandle.current = requestAnimationFrame(() => {
      rafHandle.current = null
      const buffers = textBuffers.current
      setPanels((prev) =>
        prev.map((p) => {
          const buf = buffers[p.scaffoldId]
          if (buf !== undefined && buf !== p.streamedText) {
            return { ...p, streamedText: buf }
          }
          return p
        }),
      )
    })
  }, [])

  const handleEvent = useCallback(
    (eventName: string, data: unknown) => {
      const d = data as Record<string, unknown>
      const sid = d.scaffold_id as string | undefined

      switch (eventName) {
        case 'run_started':
          setIsRunning(true)
          setIsCachedResult(false)
          setConnectionState('connected')
          setConnectionRetryCount(0)
          break

        case 'scaffold_started':
          if (sid) updatePanel(sid, { status: 'running', phase: 'started' })
          break

        case 'scaffold_phase':
          if (sid) {
            const e = d as unknown as ScaffoldPhaseEvent
            updatePanel(sid, { phase: e.phase })
          }
          break

        case 'scaffold_delta':
          if (sid) {
            const e = d as unknown as ScaffoldDeltaEvent
            const current = textBuffers.current[sid] ?? ''
            textBuffers.current[sid] = current + e.delta
            scheduleFlush()
          }
          break

        case 'scaffold_completed':
          if (sid) {
            const e = d as unknown as ScaffoldCompletedEvent
            textBuffers.current[sid] = e.output
            updatePanel(sid, {
              status: 'completed',
              output: e.output,
              streamedText: e.output,
              metrics: e.metrics,
            })
          }
          break

        case 'scaffold_failed':
          if (sid) {
            updatePanel(sid, {
              status: 'failed',
              error: (d.error as string) ?? 'Unknown error',
            })
          }
          break

        case 'evaluation_completed':
          if (sid) {
            const e = d as unknown as EvaluationCompletedEvent
            updatePanel(sid, {
              evaluation: {
                total_score: e.total_score,
                breakdown: e.breakdown,
                weights: e.weights,
                notes: e.notes,
                judge: e.judge,
              },
            })
          }
          break

        case 'run_complete': {
          const e = d as unknown as RunCompleteEvent
          setWinnerId(e.winner_scaffold_id)
          setFinalResults(e.results)
          setIsRunning(false)
          setIsCachedResult(false)
          setStreamUrl(null)
          setConnectionState('idle')
          setConnectionRetryCount(0)

          // Mark winner/loser
          setPanels((prev) =>
            prev.map((p) => {
              if (p.status === 'failed') return p
              if (p.scaffoldId === e.winner_scaffold_id) {
                return { ...p, status: 'winner' }
              }
              return { ...p, status: 'loser' }
            }),
          )
          break
        }
      }
    },
    [updatePanel, scheduleFlush],
  )

  const hydrateFromResults = useCallback(
    (
      results: RunResults,
      hydratedWinnerId: string | null,
      options?: { cached?: boolean },
    ) => {
      const cached = options?.cached ?? false
      setFinalResults(results)
      setWinnerId(hydratedWinnerId)
      setIsCachedResult(cached)
      setIsRunning(false)
      setStreamUrl(null)
      setPanels((prev) =>
        prev.map((panel) => {
          const result = results[panel.scaffoldId]
          if (!result) return panel
          const status =
            panel.scaffoldId === hydratedWinnerId ? 'winner' : ('loser' as const)
          return {
            ...panel,
            status,
            output: result.output,
            streamedText: result.output,
            metrics: result.metrics,
            evaluation: result.evaluation,
            error: result.error ?? null,
          }
        }),
      )
    },
    [],
  )

  const hydrateFromRecord = useCallback(async (): Promise<boolean> => {
    if (!runId) return false
    try {
      const raw = await fetchRunDetails(runId)
      const record = parseRunDetailsResponse(raw)
      const results = (record.results ?? {}) as RunResults
      const hasResults = Object.keys(results).length > 0
      if (!hasResults) return false
      const hydratedWinner = (record.winner_id as string | null) ?? null
      hydrateFromResults(results, hydratedWinner, { cached: false })
      setRunError(null)
      setConnectionState('idle')
      setConnectionRetryCount(0)
      return true
    } catch {
      return false
    }
  }, [hydrateFromResults, runId])

  useSSE(streamUrl, handleEvent, {
    onConnected: () => {
      setConnectionState('connected')
      setConnectionRetryCount(0)
    },
    onRetrying: (attempt) => {
      setConnectionState('retrying')
      setConnectionRetryCount(attempt)
      void hydrateFromRecord().then((recovered) => {
        if (!recovered) return
        setStreamUrl(null)
        setConnectionState('idle')
        setConnectionRetryCount(0)
      })
    },
    onFailed: () => {
      setStreamUrl(null)
      void hydrateFromRecord().then((recovered) => {
        if (recovered) return
        setConnectionState('failed')
        setIsRunning(false)
        setRunError('Connection failed while streaming run events.')
      })
    },
  })

  const startRun = useCallback(
    async (
      taskId: string,
      modelId: string,
      options?: Record<string, unknown>,
      customTask?: Record<string, unknown>,
    ) => {
      const requestKey = JSON.stringify({
        taskId,
        modelId,
        options: options ?? null,
        customTask: customTask ?? null,
        scaffoldIds: scaffolds.map((s) => s.id),
      })
      const lastReq = lastStartRequestRef.current
      if (
        lastReq &&
        lastReq.key === requestKey &&
        Date.now() - lastReq.startedAtMs < 4000
      ) {
        return
      }
      if (startInFlightRef.current || isRunning) return
      startInFlightRef.current = true
      lastStartRequestRef.current = {
        key: requestKey,
        startedAtMs: Date.now(),
      }

      // Reset state
      textBuffers.current = {}
      setRunError(null)
      setIsCachedResult(false)
      setConnectionState('idle')
      setConnectionRetryCount(0)
      setWinnerId(null)
      setFinalResults(null)
      setPanels(scaffolds.map(initPanel))
      setIsRunning(true)

      const scaffoldIds = scaffolds.map((s) => s.id)
      try {
        const result = await createArenaRun({
          task_id: taskId,
          model_id: modelId,
          scaffold_ids: scaffoldIds,
          options,
          ...(customTask ? { custom_task: customTask } : {}),
        })

        setRunId(result.run_id)
        setStreamUrl(getEventStreamUrl(result.run_id))
      } catch (err) {
        setIsRunning(false)
        setStreamUrl(null)
        const message = err instanceof Error ? err.message : 'Failed to start run.'
        setRunError(message)
        throw err
      } finally {
        startInFlightRef.current = false
      }
    },
    [isRunning, scaffolds],
  )

  const cancel = useCallback(async () => {
    if (runId) {
      await cancelRun(runId)
      setIsRunning(false)
      setStreamUrl(null)
      setConnectionState('idle')
      setConnectionRetryCount(0)
      setRunError(null)
      textBuffers.current = {}
      setPanels(scaffolds.map(initPanel))
    }
  }, [runId, scaffolds])

  const retryConnection = useCallback(() => {
    if (!runId) return
    setConnectionState('idle')
    setConnectionRetryCount(0)
    setIsRunning(true)
    setStreamUrl(getEventStreamUrl(runId))
  }, [runId])

  return {
    panels,
    runId,
    winnerId,
    finalResults,
    isRunning,
    isCachedResult,
    runError,
    connectionState,
    connectionRetryCount,
    startRun,
    cancel,
    retryConnection,
    hydrateFromResults,
    updatePanel,
    setPanels,
  }
}
