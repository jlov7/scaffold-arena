import { useState, useCallback, useRef } from 'react'
import { createArenaRun, cancelRun, getEventStreamUrl } from '../api/client'
import { useSSE } from './useSSE'
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
          setStreamUrl(null)

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

  useSSE(streamUrl, handleEvent)

  const startRun = useCallback(
    async (taskId: string, modelId: string) => {
      // Reset state
      textBuffers.current = {}
      setWinnerId(null)
      setFinalResults(null)
      setPanels(scaffolds.map(initPanel))

      const scaffoldIds = scaffolds.map((s) => s.id)
      const result = await createArenaRun({
        task_id: taskId,
        model_id: modelId,
        scaffold_ids: scaffoldIds,
      })

      setRunId(result.run_id)
      setStreamUrl(getEventStreamUrl(result.run_id))
    },
    [scaffolds],
  )

  const cancel = useCallback(async () => {
    if (runId) {
      await cancelRun(runId)
      setIsRunning(false)
    }
  }, [runId])

  return {
    panels,
    runId,
    winnerId,
    finalResults,
    isRunning,
    startRun,
    cancel,
    updatePanel,
    setPanels,
  }
}
