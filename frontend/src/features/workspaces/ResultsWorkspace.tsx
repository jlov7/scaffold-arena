import { Suspense, lazy } from 'react'
import { ScoreDashboard } from '../../components/ScoreDashboard'
import { WorkspaceSection } from '../../components/layout/WorkspaceSection'
import RunTimeline from '../../components/RunTimeline'
import StateCallout from '../../components/StateCallout'
import { COPY } from '../../content/copy'
import type { UiStateDescriptor } from '../states/taxonomy'
import type { RunResults, RunTimelineEvent } from '../../types'
import type { UserProfile } from '../../components/journey/ExperienceModeCard'
import type { RoleResultsSummary } from '../results/roleSummary'

const ProofComparison = lazy(() => import('../../components/ProofComparison'))
const DiffView = lazy(() => import('../../components/DiffView'))

type ResultsWorkspaceLane = 'summary' | 'diagnostics'

const RESULTS_LANE_COPY: Record<
  ResultsWorkspaceLane,
  { label: string; description: string }
> = {
  summary: {
    label: 'Summary',
    description: 'Decision-first view: score, cost, and role-specific recommendation.',
  },
  diagnostics: {
    label: 'Diagnostics',
    description: 'Evidence-first view: autopsy guidance, diffs, and proof comparison.',
  },
}

const PROFILE_AUDIENCE_LABEL: Record<UserProfile, string> = {
  evaluator: 'Evaluator',
  operator: 'Operator',
  analyst: 'Analyst',
  executive: 'Executive',
}

interface ComparisonCaseDisplay {
  case_id: string
  label: string
  model_id: string
  scaffold_id: string
  score: number
  cost: number
}

export interface RunDeltaSummary {
  previousWinnerId: string | null
  currentWinnerId: string | null
  winnerChanged: boolean
  totalCostDeltaUsd: number
  scoreDeltas: Array<{ scaffoldId: string; delta: number }>
}

export interface ResultsWorkspaceProps {
  compactMode: boolean
  onToggleCompactMode: () => void
  resultsLane: ResultsWorkspaceLane
  onResultsLaneChange: (lane: ResultsWorkspaceLane) => void
  resultsUiState: UiStateDescriptor
  resultsStateAction: { label: string; run: () => void } | null
  historyHydrationPending: boolean
  finalResults: RunResults | null
  winnerId: string | null
  isCachedResult: boolean
  scaffoldNames: Record<string, string>
  userProfile: UserProfile
  roleResultsSummary: RoleResultsSummary | null
  shouldShowAutopsyGuide: boolean
  firstAutopsyTargetId: string | null
  comparisonCases: ComparisonCaseDisplay[]
  comparisonLoading: boolean
  deferredResultsReady: boolean
  timelineEvents: RunTimelineEvent[]
  runDeltaSummary: RunDeltaSummary | null
  onRunComparison: (winnerId: string) => Promise<void>
  onRunAutopsy: (scaffoldId: string) => Promise<void>
  onExportReport: () => Promise<void>
  onExportBundle: () => Promise<void>
  onExportJson: () => void
  onShare: () => Promise<void>
  onNavigateToArena: () => void
  onNavigateToHistory: () => void
  onOpenHelpCenter: (source: 'header' | 'banner' | 'keyboard' | 'card' | 'route' | 'unknown') => void
  onSetAutopsyGuideDismissed: (dismissed: boolean) => void
}

export function ResultsWorkspace({
  compactMode,
  onToggleCompactMode,
  resultsLane,
  onResultsLaneChange,
  resultsUiState,
  resultsStateAction,
  historyHydrationPending,
  finalResults,
  winnerId,
  isCachedResult,
  scaffoldNames,
  userProfile,
  roleResultsSummary,
  shouldShowAutopsyGuide,
  firstAutopsyTargetId,
  comparisonCases,
  comparisonLoading,
  deferredResultsReady,
  timelineEvents,
  runDeltaSummary,
  onRunComparison,
  onRunAutopsy,
  onExportReport,
  onExportBundle,
  onExportJson,
  onShare,
  onNavigateToArena,
  onNavigateToHistory,
  onOpenHelpCenter,
  onSetAutopsyGuideDismissed,
}: ResultsWorkspaceProps) {
  return (
    <section
      className={compactMode ? 'space-y-3' : 'space-y-5'}
      aria-label="Results workspace"
    >
      <h2 className="font-mono text-sm text-text-primary">Results workspace</h2>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-[10px] uppercase tracking-widest text-text-secondary">
          Results workspace
        </div>
        <button
          type="button"
          onClick={onToggleCompactMode}
          className="rounded border border-border px-2.5 py-1 text-[11px] font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
        >
          {compactMode ? 'Disable compact mode' : 'Enable compact mode'}
        </button>
      </div>
      <WorkspaceSection template="review-dense" priority="important" className="stack-tight">
        <div className="ui-heading-sm text-text-secondary">
          Results workflow lane
        </div>
        <div className="grid gap-2 sm:grid-cols-2">
          {(['summary', 'diagnostics'] as ResultsWorkspaceLane[]).map((lane) => (
            <button
              key={lane}
              type="button"
              onClick={() => onResultsLaneChange(lane)}
              className={[
                'rounded border px-3 py-2 text-left text-xs font-mono transition-colors',
                resultsLane === lane
                  ? 'border-accent-info bg-accent-info/10 text-accent-info'
                  : 'border-border text-text-secondary hover:border-accent-info hover:text-accent-info',
              ].join(' ')}
            >
              {RESULTS_LANE_COPY[lane].label}
            </button>
          ))}
        </div>
        <p className="text-xs text-text-secondary">
          {RESULTS_LANE_COPY[resultsLane].description}
        </p>
      </WorkspaceSection>
      <StateCallout
        kind={resultsUiState.kind}
        title={resultsUiState.title}
        description={resultsUiState.description}
        actionLabel={resultsStateAction?.label}
        onAction={resultsStateAction?.run}
      />
      {historyHydrationPending && (
        <StateCallout
          kind="loading"
          title="Loading selected run"
          description="Hydrating prior run context so scoreboards and evidence are ready."
        />
      )}
      {!finalResults && (
        <div className="max-w-3xl rounded-lg border border-border bg-bg-secondary p-5">
          <h3 className="font-mono text-sm text-text-primary">No results loaded yet</h3>
          <p className="mt-2 text-xs text-text-secondary">
            {COPY.emptyStates.results}
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onNavigateToArena}
              className="rounded border border-accent-info px-3 py-1.5 text-xs font-mono text-accent-info hover:bg-accent-info/20"
            >
              Start a new arena run
            </button>
            <button
              type="button"
              onClick={onNavigateToHistory}
              className="rounded border border-border px-3 py-1.5 text-xs font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Load from history
            </button>
            <button
              type="button"
              onClick={() => onOpenHelpCenter('route')}
              className="rounded border border-border px-3 py-1.5 text-xs font-mono text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Open help center
            </button>
          </div>
        </div>
      )}

      {finalResults && resultsLane === 'summary' && (
        <>
          {runDeltaSummary && (
            <WorkspaceSection template="review-dense" priority="important" className="font-mono stack-tight">
              <div className="ui-heading-sm text-text-secondary">
                What changed since your previous run
              </div>
              <div className="text-xs text-text-secondary">
                Winner:{' '}
                {runDeltaSummary.currentWinnerId ?? 'none'}
                {runDeltaSummary.winnerChanged ? ' (changed)' : ' (unchanged)'}
              </div>
              <div className="text-xs text-text-secondary">
                Total cost delta: {runDeltaSummary.totalCostDeltaUsd >= 0 ? '+' : ''}
                ${runDeltaSummary.totalCostDeltaUsd.toFixed(4)}
              </div>
              {runDeltaSummary.scoreDeltas.length > 0 && (
                <div className="grid gap-1 text-[11px] text-text-secondary sm:grid-cols-2">
                  {runDeltaSummary.scoreDeltas.slice(0, 6).map((entry) => (
                    <div key={entry.scaffoldId}>
                      {entry.scaffoldId}: {entry.delta >= 0 ? '+' : ''}
                      {entry.delta.toFixed(1)}
                    </div>
                  ))}
                </div>
              )}
            </WorkspaceSection>
          )}

          {roleResultsSummary && (
            <WorkspaceSection template="review-dense" priority="important" className="font-mono stack-tight">
              <div className="ui-heading-sm text-text-secondary">
                Role summary: {PROFILE_AUDIENCE_LABEL[userProfile]}
              </div>
              <h3 className="ui-heading-lg text-text-primary">
                {roleResultsSummary.title}
              </h3>
              <p className="text-xs text-text-secondary">
                {roleResultsSummary.body}
              </p>
              <ul className="list-disc space-y-1 pl-4 text-xs text-text-secondary">
                {roleResultsSummary.details.map((detail) => (
                  <li key={detail}>{detail}</li>
                ))}
              </ul>
            </WorkspaceSection>
          )}

          {shouldShowAutopsyGuide && firstAutopsyTargetId && (
            <WorkspaceSection template="review-dense" priority="important" className="font-mono stack-tight">
              <div className="ui-heading-sm text-accent-info">
                First autopsy walkthrough
              </div>
              <p className="text-xs text-text-secondary">
                Start from summary for a fast diagnostic handoff, or open the diagnostics lane for full evidence context.
              </p>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void onRunAutopsy(firstAutopsyTargetId)
                  }}
                  className="rounded border border-accent-info/70 px-3 py-1.5 text-xs text-accent-info hover:bg-accent-info/15"
                >
                  Start first autopsy
                </button>
                <button
                  type="button"
                  onClick={() => onResultsLaneChange('diagnostics')}
                  className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
                >
                  Open diagnostics lane
                </button>
              </div>
            </WorkspaceSection>
          )}

          <ScoreDashboard
            results={finalResults}
            winnerId={winnerId}
            isCached={isCachedResult}
            scaffoldNames={scaffoldNames}
            onRunComparison={onRunComparison}
            onRunAutopsy={onRunAutopsy}
            onExportReport={onExportReport}
            onExportBundle={onExportBundle}
            onExportJson={onExportJson}
            onShare={onShare}
          />

          <WorkspaceSection template="review-dense" priority="optional" className="font-mono stack-tight">
            <div className="ui-heading-sm text-text-secondary">
              Need deeper proof?
            </div>
            <p className="text-xs text-text-secondary">
              Open Diagnostics when you need failure evidence, autopsy patches, or side-by-side diff reasoning.
            </p>
            <button
              type="button"
              onClick={() => onResultsLaneChange('diagnostics')}
              className="rounded border border-accent-info px-3 py-1.5 text-xs text-accent-info hover:bg-accent-info/15"
            >
              Open diagnostics lane
            </button>
          </WorkspaceSection>
        </>
      )}

      {finalResults && resultsLane === 'diagnostics' && (
        <>
          {shouldShowAutopsyGuide && firstAutopsyTargetId && (
            <WorkspaceSection template="review-dense" priority="critical" className="font-mono stack-tight">
              <div className="ui-heading-sm text-accent-info">
                First autopsy walkthrough
              </div>
              <h3 className="ui-heading-lg text-text-primary">
                Diagnose one scaffold before applying a patch
              </h3>
              <ol className="list-decimal space-y-1 pl-4 text-xs text-text-secondary">
                <li>Open autopsy for a non-winning scaffold.</li>
                <li>Review concrete failure evidence and generated patch.</li>
                <li>Apply patch and rerun to confirm improvement.</li>
              </ol>
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  onClick={() => {
                    void onRunAutopsy(firstAutopsyTargetId)
                  }}
                  className="rounded border border-accent-info/70 px-3 py-1.5 text-xs text-accent-info hover:bg-accent-info/15"
                >
                  Start first autopsy
                </button>
                <button
                  type="button"
                  onClick={() => onSetAutopsyGuideDismissed(true)}
                  className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
                >
                  Dismiss walkthrough
                </button>
              </div>
            </WorkspaceSection>
          )}

          <WorkspaceSection template="review-dense" priority="optional" className="font-mono stack-tight">
            <div className="ui-heading-sm text-text-secondary">
              Diagnostics lane
            </div>
            <p className="text-xs text-text-secondary">
              You are in evidence mode. Return to Summary for top-line winner and export decisions.
            </p>
            <button
              type="button"
              onClick={() => onResultsLaneChange('summary')}
              className="rounded border border-border px-3 py-1.5 text-xs text-text-secondary hover:border-accent-info hover:text-accent-info"
            >
              Back to summary lane
            </button>
          </WorkspaceSection>

          {deferredResultsReady ? (
            <>
              <RunTimeline events={timelineEvents} />

              <Suspense fallback={<div className="text-xs text-text-muted">Loading diff...</div>}>
                <DiffView results={finalResults} scaffoldNames={scaffoldNames} />
              </Suspense>

              {(comparisonLoading || comparisonCases.length > 0) && (
                <Suspense fallback={<div className="text-xs text-text-muted">Loading comparison...</div>}>
                  <ProofComparison cases={comparisonCases} isLoading={comparisonLoading} />
                </Suspense>
              )}
            </>
          ) : (
            <div className="rounded border border-border/60 bg-bg-secondary p-3">
              <div className="text-[10px] uppercase tracking-widest text-text-muted">
                Loading supporting analysis
              </div>
              <div className="mt-2 h-2 w-2/3 rounded bg-bg-tertiary skeleton-shimmer" />
              <div className="mt-2 h-2 w-1/2 rounded bg-bg-tertiary skeleton-shimmer" />
            </div>
          )}
        </>
      )}
    </section>
  )
}
