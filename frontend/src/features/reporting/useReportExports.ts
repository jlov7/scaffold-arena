import { useCallback, useState, type RefObject } from 'react'

import { exportRunBundle, generateReport } from '../../api/client'
import { trackEvent } from '../../telemetry/tracker'
import type { AutopsyResult, RunResults } from '../../types'
import type { ComparisonCaseDisplay } from '../comparison/useComparison'

interface UseReportExportsOptions {
  finalResults: RunResults | null
  winnerId: string | null
  runId: string | null
  comparisonCases: ComparisonCaseDisplay[]
  autopsyResult: AutopsyResult | null
  lastRunRef: RefObject<{ taskId: string; modelId: string }>
  getErrorMessage: (error: unknown) => string
  pushToast: (type: 'error' | 'success' | 'info', message: string) => void
  setOperationError: (message: string | null) => void
}

function download(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export function useReportExports({
  finalResults,
  winnerId,
  runId,
  comparisonCases,
  autopsyResult,
  lastRunRef,
  getErrorMessage,
  pushToast,
  setOperationError,
}: UseReportExportsOptions) {
  const [hasExported, setHasExported] = useState(false)
  const [reportOpen, setReportOpen] = useState(false)
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null)
  const [reportPdf, setReportPdf] = useState<string | null>(null)
  const [reportLoading, setReportLoading] = useState(false)

  const exportReport = useCallback(async () => {
    if (!finalResults) return
    setReportOpen(true)
    setReportMarkdown(null)
    setReportPdf(null)
    setReportLoading(true)
    setOperationError(null)
    try {
      const report = await generateReport({
        task_id: lastRunRef.current.taskId,
        model_id: lastRunRef.current.modelId,
        results: finalResults as unknown as Record<string, unknown>,
        comparison: comparisonCases.length > 0 ? { cases: comparisonCases } : null,
        autopsy: autopsyResult ? (autopsyResult as unknown as Record<string, unknown>) : null,
      })
      setReportMarkdown(report.markdown)
      setReportPdf(report.pdf_base64)
      pushToast('success', 'Report generated')
      setHasExported(true)
      trackEvent('report_exported', { has_pdf: Boolean(report.pdf_base64) })
    } catch (error) {
      setReportMarkdown('# Error\n\nFailed to generate report.')
      const message = `Report generation failed: ${getErrorMessage(error)}`
      setOperationError(message)
      pushToast('error', message)
    } finally {
      setReportLoading(false)
    }
  }, [autopsyResult, comparisonCases, finalResults, getErrorMessage, lastRunRef, pushToast, setOperationError])

  const exportJson = useCallback(() => {
    if (!finalResults) return
    const payload = {
      task_id: lastRunRef.current.taskId,
      model_id: lastRunRef.current.modelId,
      winner_id: winnerId,
      results: finalResults,
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const fileTask = (lastRunRef.current.taskId || 'task').replace(/[^a-zA-Z0-9_-]/g, '-')
    download(new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' }), `scaffold-arena-${fileTask}-${timestamp}.json`)
    pushToast('success', 'JSON exported')
    trackEvent('json_exported', { task_id: lastRunRef.current.taskId, has_winner: Boolean(winnerId) })
  }, [finalResults, lastRunRef, pushToast, winnerId])

  const exportBundle = useCallback(async () => {
    if (!runId) {
      pushToast('error', 'No run selected to export.')
      return
    }
    try {
      download(await exportRunBundle(runId), `scaffold-arena-${runId}-bundle.zip`)
      pushToast('success', 'Export bundle downloaded')
    } catch (error) {
      const message = `Bundle export failed: ${getErrorMessage(error)}`
      setOperationError(message)
      pushToast('error', message)
    }
  }, [getErrorMessage, pushToast, runId, setOperationError])

  const shareRun = useCallback(async () => {
    try {
      const shareUrl = window.location.href
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl)
      } else {
        const element = document.createElement('textarea')
        element.value = shareUrl
        document.body.appendChild(element)
        element.select()
        document.execCommand('copy')
        document.body.removeChild(element)
      }
      pushToast('success', 'Run URL copied')
      trackEvent('run_shared', { run_id: runId })
    } catch {
      pushToast('error', 'Failed to copy run URL')
    }
  }, [pushToast, runId])

  return {
    exportBundle,
    exportJson,
    exportReport,
    hasExported,
    reportLoading,
    reportMarkdown,
    reportOpen,
    reportPdf,
    setReportOpen,
    shareRun,
  }
}
