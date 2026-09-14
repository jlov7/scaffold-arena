import { useCallback, useState, type RefObject } from 'react'

import { createPatchRerun, runAutopsy } from '../../api/client'
import { trackEvent } from '../../telemetry/tracker'
import type { AutopsyResult, RunResults } from '../../types'

interface AutopsyTarget {
  scaffoldId: string
  scaffoldName: string
}

interface UseAutopsyOptions {
  finalResults: RunResults | null
  scaffoldNames: Record<string, string>
  lastRunRef: RefObject<{ taskId: string; modelId: string }>
  getErrorMessage: (error: unknown) => string
  pushToast: (type: 'error' | 'success' | 'info', message: string) => void
  setOperationError: (message: string | null) => void
  onStart: () => void
}

export function useAutopsy({
  finalResults,
  scaffoldNames,
  lastRunRef,
  getErrorMessage,
  pushToast,
  setOperationError,
  onStart,
}: UseAutopsyOptions) {
  const [autopsyTarget, setAutopsyTarget] = useState<AutopsyTarget | null>(null)
  const [autopsyResult, setAutopsyResult] = useState<AutopsyResult | null>(null)
  const [autopsyLoading, setAutopsyLoading] = useState(false)

  const runAutopsyForScaffold = useCallback(async (scaffoldId: string) => {
    if (!finalResults) return
    const result = finalResults[scaffoldId]
    if (!result) return
    onStart()
    setAutopsyTarget({ scaffoldId, scaffoldName: scaffoldNames[scaffoldId] ?? scaffoldId })
    setAutopsyResult(null)
    setAutopsyLoading(true)
    setOperationError(null)
    trackEvent('autopsy_started', { scaffold_id: scaffoldId, task_id: lastRunRef.current.taskId })
    try {
      const autopsy = await runAutopsy({
        task_id: lastRunRef.current.taskId,
        scaffold_id: scaffoldId,
        output: result.output,
        evaluation: result.evaluation as unknown as Record<string, unknown>,
        metrics: result.metrics as unknown as Record<string, unknown>,
      })
      setAutopsyResult(autopsy)
    } catch (error) {
      setAutopsyResult({ failures: [], patch: {}, summary: 'Failed to analyze.' })
      const message = `Autopsy failed: ${getErrorMessage(error)}`
      setOperationError(message)
      pushToast('error', message)
    } finally {
      setAutopsyLoading(false)
    }
  }, [finalResults, getErrorMessage, lastRunRef, onStart, pushToast, scaffoldNames, setOperationError])

  const applyPatch = useCallback(async (patch: Record<string, unknown>) => {
    if (!autopsyTarget) return
    try {
      await createPatchRerun({
        task_id: lastRunRef.current.taskId,
        model_id: lastRunRef.current.modelId,
        scaffold_id: autopsyTarget.scaffoldId,
        patch,
      })
      setAutopsyTarget(null)
    } catch (error) {
      const message = `Patch rerun failed: ${getErrorMessage(error)}`
      setOperationError(message)
      pushToast('error', message)
    }
  }, [autopsyTarget, getErrorMessage, lastRunRef, pushToast, setOperationError])

  const resetAutopsy = useCallback(() => {
    setAutopsyTarget(null)
    setAutopsyResult(null)
  }, [])

  return {
    applyPatch,
    autopsyLoading,
    autopsyResult,
    autopsyTarget,
    closeAutopsy: () => setAutopsyTarget(null),
    resetAutopsy,
    runAutopsyForScaffold,
  }
}
