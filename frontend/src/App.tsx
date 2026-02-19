import { useState, useEffect, useCallback, useRef, useMemo } from 'react'
import {
  fetchMeta,
  createComparison,
  runAutopsy,
  createPatchRerun,
  generateReport,
} from './api/client'
import { useArenaRun } from './hooks/useArenaRun'
import { useSSE } from './hooks/useSSE'
import { TaskSelector } from './components/TaskSelector'
import ArenaGrid from './components/ArenaGrid'
import { ScoreDashboard } from './components/ScoreDashboard'
import ProofComparison from './components/ProofComparison'
import AutopsyModal from './components/AutopsyModal'
import ReportModal from './components/ReportModal'
import type { AppMeta, AutopsyResult, RunMetrics } from './types'

interface ComparisonCaseDisplay {
  case_id: string
  label: string
  model_id: string
  scaffold_id: string
  score: number
  cost: number
  metrics?: RunMetrics
}

function caseLabel(caseId: string): string {
  switch (caseId) {
    case 'cheap_winning':
      return 'Cheap Model + Winner'
    case 'expensive_bare':
      return 'Expensive + Bare'
    case 'expensive_winning':
      return 'Expensive + Winner'
    default:
      return caseId
  }
}

const CASE_ORDER = ['cheap_winning', 'expensive_bare', 'expensive_winning']

export default function App() {
  // --- Meta ---
  const [meta, setMeta] = useState<AppMeta | null>(null)
  const [metaError, setMetaError] = useState<string | null>(null)

  useEffect(() => {
    fetchMeta().then(setMeta).catch((err) => setMetaError(err.message))
  }, [])

  const scaffolds = useMemo(() => meta?.scaffolds ?? [], [meta])
  const tasks = useMemo(() => meta?.tasks ?? [], [meta])
  const models = useMemo(() => meta?.models ?? [], [meta])

  // --- Arena run ---
  const {
    panels,
    winnerId,
    finalResults,
    isRunning,
    startRun,
    cancel,
    setPanels,
  } = useArenaRun(scaffolds)

  // Initialize panels when scaffolds load
  useEffect(() => {
    if (scaffolds.length > 0) {
      setPanels(
        scaffolds.map((s) => ({
          scaffoldId: s.id,
          scaffoldName: s.name,
          status: 'idle' as const,
          phase: '',
          streamedText: '',
          output: '',
          metrics: null,
          evaluation: null,
          error: null,
        })),
      )
    }
  }, [scaffolds, setPanels])

  // Track last run params for comparison/report
  const lastRunRef = useRef({ taskId: '', modelId: '' })
  const [hasEverRun, setHasEverRun] = useState(false)

  const scaffoldNames = useMemo(
    () => Object.fromEntries(scaffolds.map((s) => [s.id, s.name])),
    [scaffolds],
  )

  const handleRun = useCallback(
    (taskId: string, modelId: string) => {
      lastRunRef.current = { taskId, modelId }
      setHasEverRun(true)
      setComparisonCases([])
      setComparisonLoading(false)
      setComparisonStreamUrl(null)
      setAutopsyTarget(null)
      setAutopsyResult(null)
      startRun(taskId, modelId)
    },
    [startRun],
  )

  // --- Comparison ---
  const [comparisonStreamUrl, setComparisonStreamUrl] = useState<string | null>(
    null,
  )
  const [comparisonLoading, setComparisonLoading] = useState(false)
  const [comparisonCases, setComparisonCases] = useState<
    ComparisonCaseDisplay[]
  >([])

  const handleComparisonEvent = useCallback(
    (eventName: string, data: unknown) => {
      const d = data as Record<string, unknown>

      switch (eventName) {
        case 'comparison_started':
          setComparisonLoading(true)
          break

        case 'comparison_complete': {
          const results = d.results as Record<
            string,
            Record<string, unknown>
          >
          const cases: ComparisonCaseDisplay[] = CASE_ORDER.filter(
            (cid) => cid in results,
          ).map((cid) => {
            const r = results[cid]
            const metrics = r.metrics as RunMetrics | undefined
            const evaluation = r.evaluation as
              | Record<string, unknown>
              | undefined
            return {
              case_id: cid,
              label: caseLabel(cid),
              model_id: r.model_id as string,
              scaffold_id: r.scaffold_id as string,
              score: (evaluation?.total_score as number) ?? 0,
              cost: metrics?.cost_usd ?? 0,
              metrics,
            }
          })
          setComparisonCases(cases)
          setComparisonLoading(false)
          setComparisonStreamUrl(null)
          break
        }
      }
    },
    [],
  )

  useSSE(comparisonStreamUrl, handleComparisonEvent)

  const handleRunComparison = useCallback(
    async (winningScaffoldId: string) => {
      const { taskId, modelId } = lastRunRef.current
      if (!taskId) return

      setComparisonCases([])
      setComparisonLoading(true)

      try {
        const result = await createComparison({
          task_id: taskId,
          expensive_model_id: modelId,
          cheap_model_id: 'claude-haiku-4-5',
          winning_scaffold_id: winningScaffoldId,
        })
        setComparisonStreamUrl(result.stream_url)
      } catch {
        setComparisonLoading(false)
      }
    },
    [],
  )

  // --- Autopsy ---
  const [autopsyTarget, setAutopsyTarget] = useState<{
    scaffoldId: string
    scaffoldName: string
  } | null>(null)
  const [autopsyResult, setAutopsyResult] = useState<AutopsyResult | null>(
    null,
  )
  const [autopsyLoading, setAutopsyLoading] = useState(false)

  const handleRunAutopsy = useCallback(
    async (scaffoldId: string) => {
      if (!finalResults) return
      const result = finalResults[scaffoldId]
      if (!result) return

      const scaffoldName =
        scaffolds.find((s) => s.id === scaffoldId)?.name ?? scaffoldId
      setAutopsyTarget({ scaffoldId, scaffoldName })
      setAutopsyResult(null)
      setAutopsyLoading(true)

      try {
        const autopsy = await runAutopsy({
          task_id: lastRunRef.current.taskId,
          scaffold_id: scaffoldId,
          output: result.output,
          evaluation: result.evaluation as unknown as Record<string, unknown>,
          metrics: result.metrics as unknown as Record<string, unknown>,
        })
        setAutopsyResult(autopsy)
      } catch {
        setAutopsyResult({
          failures: [],
          patch: {},
          summary: 'Failed to analyze.',
        })
      } finally {
        setAutopsyLoading(false)
      }
    },
    [finalResults, scaffolds],
  )

  const handleApplyPatch = useCallback(
    async (patch: Record<string, unknown>) => {
      if (!autopsyTarget) return

      try {
        await createPatchRerun({
          task_id: lastRunRef.current.taskId,
          model_id: lastRunRef.current.modelId,
          scaffold_id: autopsyTarget.scaffoldId,
          patch,
        })
        setAutopsyTarget(null)
      } catch {
        // Patch rerun failed silently — future iteration can show error
      }
    },
    [autopsyTarget],
  )

  // --- Report ---
  const [reportOpen, setReportOpen] = useState(false)
  const [reportMarkdown, setReportMarkdown] = useState<string | null>(null)
  const [reportPdf, setReportPdf] = useState<string | null>(null)
  const [reportLoading, setReportLoading] = useState(false)

  const handleExportReport = useCallback(async () => {
    if (!finalResults) return

    setReportOpen(true)
    setReportMarkdown(null)
    setReportPdf(null)
    setReportLoading(true)

    try {
      const report = await generateReport({
        task_id: lastRunRef.current.taskId,
        model_id: lastRunRef.current.modelId,
        results: finalResults as unknown as Record<string, unknown>,
        comparison:
          comparisonCases.length > 0 ? { cases: comparisonCases } : null,
        autopsy: autopsyResult
          ? (autopsyResult as unknown as Record<string, unknown>)
          : null,
      })
      setReportMarkdown(report.markdown)
      setReportPdf(report.pdf_base64)
    } catch {
      setReportMarkdown('# Error\n\nFailed to generate report.')
    } finally {
      setReportLoading(false)
    }
  }, [finalResults, comparisonCases, autopsyResult])

  // --- Loading / Error states ---
  if (metaError) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center font-mono">
        <div className="text-center">
          <div className="text-accent-loser text-sm mb-2">
            Failed to connect
          </div>
          <div className="text-text-secondary text-xs">{metaError}</div>
        </div>
      </div>
    )
  }

  if (!meta) {
    return (
      <div className="min-h-screen bg-bg-primary flex items-center justify-center font-mono">
        <div className="text-text-secondary text-sm animate-pulse">
          Connecting to arena...
        </div>
      </div>
    )
  }

  // --- Main render ---
  return (
    <div className="min-h-screen bg-bg-primary flex flex-col">
      <header className="border-b border-border relative">
        <div className="absolute top-0 left-0 right-0 h-[2px] bg-gradient-to-r from-accent-info via-accent-winner to-accent-warning" />
        <div className="px-6 py-4">
          <h1 className="font-mono text-2xl font-bold tracking-tight text-text-primary">
            SCAFFOLD ARENA
          </h1>
          <p className="font-mono text-sm text-text-secondary mt-1">
            Same model, different scaffolding &mdash; wildly different results
          </p>
        </div>
      </header>

      <TaskSelector
        tasks={tasks}
        models={models}
        isRunning={isRunning}
        onRun={handleRun}
        onCancel={cancel}
      />

      <main className="flex-1 p-6 space-y-6">
        {/* Onboarding: How it works — shown before first run */}
        {!hasEverRun && !isRunning && (
          <div className="rounded-lg border border-border/50 bg-bg-secondary/50 p-6">
            <div className="text-[10px] text-text-muted uppercase tracking-widest font-mono mb-5">
              How it works
            </div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
              <div>
                <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                  01 &mdash; Select a task
                </div>
                <p className="text-xs text-text-secondary leading-relaxed">
                  Each task challenges a different AI capability &mdash; structured extraction, risk analysis, or research synthesis.
                </p>
              </div>
              <div>
                <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                  02 &mdash; Run the Arena
                </div>
                <p className="text-xs text-text-secondary leading-relaxed">
                  Four scaffold architectures run simultaneously on the same model and prompt. Watch tokens stream in real time.
                </p>
              </div>
              <div>
                <div className="text-accent-info font-mono text-sm font-bold mb-1.5">
                  03 &mdash; Prove the value
                </div>
                <p className="text-xs text-text-secondary leading-relaxed">
                  Compare scores, diagnose failures, and prove that a cheap model with good scaffolding beats an expensive model without it.
                </p>
              </div>
            </div>
          </div>
        )}

        <ArenaGrid panels={panels} />

        {finalResults && !isRunning && (
          <ScoreDashboard
            results={finalResults}
            winnerId={winnerId}
            scaffoldNames={scaffoldNames}
            onRunComparison={handleRunComparison}
            onRunAutopsy={handleRunAutopsy}
            onExportReport={handleExportReport}
          />
        )}

        {(comparisonLoading || comparisonCases.length > 0) && (
          <ProofComparison
            cases={comparisonCases}
            isLoading={comparisonLoading}
          />
        )}
      </main>

      <AutopsyModal
        isOpen={autopsyTarget !== null}
        onClose={() => setAutopsyTarget(null)}
        autopsy={autopsyResult}
        isLoading={autopsyLoading}
        onApplyPatch={handleApplyPatch}
        scaffoldName={autopsyTarget?.scaffoldName ?? ''}
      />

      <ReportModal
        isOpen={reportOpen}
        onClose={() => setReportOpen(false)}
        markdown={reportMarkdown}
        pdfBase64={reportPdf}
        isLoading={reportLoading}
      />
    </div>
  )
}
