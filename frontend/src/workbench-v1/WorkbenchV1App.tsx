import { lazy, Suspense, useCallback, useEffect, useMemo, useState } from 'react'

import { arenaV1, type ArenaSession, type ExperimentDetail, type PreflightReport } from '../api/v1/client'
import { checkingRuntimeRevision, fetchRuntimeMetadata, offlineRuntimeRevision, runtimeRevisionStatus, type RuntimeRevisionStatus } from '../api/v1/runtimeMetadata'
import { DisclosureRow, StatusIndicator, WorkbenchButton, WorkbenchPanel, WorkbenchState } from './design-system'
import { fixturePack, type PackSelection } from './journeys/study-design-preflight/types'
import { WorkbenchShell, WORKBENCH_AREAS, type WorkbenchArea, type WorkbenchMode } from './shell'
import { AnalyzeSurface } from './surfaces/analyze'
import { DesignSurface } from './surfaces/design'
import { EvidenceSurface } from './surfaces/evidence'
import { ExecuteSurface } from './surfaces/execute'
import { PreflightSurface } from './surfaces/preflight'
import { ReviewSurface } from './surfaces/review'
import { SettingsSurface } from './surfaces/settings'
import { StudiesSurface } from './surfaces/studies'
import { DecisionCanvas } from './surfaces/decision'
import { resolveTeamProject } from './teamProject'

const XRaySurface = lazy(() =>
  import('./surfaces/xray').then(({ XRaySurface }) => ({ default: XRaySurface })),
)
const ObservatorySurface = lazy(() =>
  import('./surfaces/observatory').then(({ ObservatorySurface }) => ({
    default: ObservatorySurface,
  })),
)
const CounterfactualSurface = lazy(() =>
  import('./surfaces/counterfactual').then(({ CounterfactualSurface }) => ({
    default: CounterfactualSurface,
  })),
)
const ForgeSurface = lazy(() =>
  import('./surfaces/forge').then(({ ForgeSurface }) => ({ default: ForgeSurface })),
)
const TraceLabSurface = lazy(() =>
  import('./surfaces/trace-lab').then(({ TraceLabSurface }) => ({ default: TraceLabSurface })),
)

type RouteState = {
  area: WorkbenchArea
  projectId: string | undefined
  pack: PackSelection | null
  experimentId: string | null
  executionId: string | null
  reportDigest: string | null
  leftAttemptId: string | null
  rightAttemptId: string | null
  sourceDigest: string | null
  xrayDigest: string | null
  attemptIds: string[]
  recovered: boolean
}

function readRoute(): RouteState {
  const path = window.location.pathname
  const requested = path === '/' ? 'compare' : path.split('/')[2]
  const area = WORKBENCH_AREAS.includes(requested as WorkbenchArea) ? requested as WorkbenchArea : 'compare'
  const params = new URLSearchParams(window.location.search)
  const packId = params.get('study_pack_id')
  const version = params.get('study_pack_version')
  return {
    area, projectId: params.get('project_id') ?? undefined,
    pack: packId && version ? { studyPackId: packId, version } : null,
    experimentId: params.get('experiment_id'), executionId: params.get('execution_id'), reportDigest: params.get('report_digest'),
    leftAttemptId: params.get('left_attempt_id'), rightAttemptId: params.get('right_attempt_id'),
    sourceDigest: params.get('source_digest'), xrayDigest: params.get('xray_digest'),
    attemptIds: (params.get('attempt_ids') ?? params.get('attempt_id') ?? '').split(',').filter(Boolean),
    recovered: path.startsWith('/workbench/') && requested !== area,
  }
}

function routeHref(route: RouteState): string {
  const params = new URLSearchParams()
  if (route.projectId) params.set('project_id', route.projectId)
  if (route.pack) { params.set('study_pack_id', route.pack.studyPackId); params.set('study_pack_version', route.pack.version) }
  if (route.experimentId) params.set('experiment_id', route.experimentId)
  if (route.executionId) params.set('execution_id', route.executionId)
  if (route.reportDigest) params.set('report_digest', route.reportDigest)
  if (route.leftAttemptId) params.set('left_attempt_id', route.leftAttemptId)
  if (route.rightAttemptId) params.set('right_attempt_id', route.rightAttemptId)
  if (route.sourceDigest) params.set('source_digest', route.sourceDigest)
  if (route.xrayDigest) params.set('xray_digest', route.xrayDigest)
  if (route.attemptIds.length) params.set('attempt_ids', route.attemptIds.join(','))
  const path = route.area === 'compare' ? '/' : `/workbench/${route.area}`
  return `${path}${params.size ? `?${params.toString()}` : ''}`
}

export function WorkbenchV1App() {
  const [route, setRoute] = useState(readRoute)
  const [mode, setMode] = useState<WorkbenchMode>('guided')
  const [preflightReport, setPreflightReport] = useState<PreflightReport | null>(null)
  const [sessionState, setSessionState] = useState<'loading' | 'ready' | 'error'>('loading')
  const [sessionMessage, setSessionMessage] = useState('')
  const [session, setSession] = useState<ArenaSession | null>(null)
  const [frozenAt, setFrozenAt] = useState<string | null>(null)
  const [revision, setRevision] = useState<RuntimeRevisionStatus>(() => checkingRuntimeRevision(__GIT_SHA__))

  const updateExperimentIdentity = useCallback((identity: ExperimentDetail['immutable_identity']) => {
    setFrozenAt(identity.frozen_at ?? null)
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    let active = true
    void fetchRuntimeMetadata({ signal: controller.signal }).then((metadata) => {
      if (active) setRevision(runtimeRevisionStatus(__GIT_SHA__, metadata.git_sha))
    }).catch((error: unknown) => {
      if (!active || controller.signal.aborted) return
      setRevision(offlineRuntimeRevision(__GIT_SHA__, error instanceof Error ? error.message : undefined))
    })
    return () => {
      active = false
      controller.abort()
    }
  }, [])

  useEffect(() => {
    let active = true
    void arenaV1.auth.session({ projectId: route.projectId }).then((currentSession) => {
      if (active) { setSession(currentSession); setSessionState('ready') }
    }).catch((error: unknown) => {
      if (active) { setSessionState('error'); setSessionMessage(error instanceof Error ? error.message : 'The session could not be recovered.') }
    })
    return () => { active = false }
  }, [route.projectId])

  const teamProject = resolveTeamProject(session, route.projectId)

  useEffect(() => {
    if (!route.experimentId) return
    let active = true
    void arenaV1.experiments.get(route.experimentId, { projectId: route.projectId }).then((experiment) => {
      if (active) updateExperimentIdentity(experiment.immutable_identity)
    }).catch(() => {
      if (active) setFrozenAt(null)
    })
    return () => { active = false }
  }, [route.experimentId, route.projectId, updateExperimentIdentity])

  useEffect(() => {
    if (teamProject.kind !== 'auto') return
    const timer = window.setTimeout(() => {
      const next = { ...route, projectId: teamProject.projectId }
      window.history.replaceState({}, '', routeHref(next))
      setFrozenAt(null)
      setRoute(next)
    }, 0)
    return () => window.clearTimeout(timer)
  }, [route, teamProject])

  useEffect(() => {
    const sync = () => { setRoute(readRoute()); setPreflightReport(null); setFrozenAt(null) }
    window.addEventListener('popstate', sync)
    return () => window.removeEventListener('popstate', sync)
  }, [])

  const navigate = useCallback((area: WorkbenchArea, changes: Partial<RouteState> = {}) => {
    const next = { ...route, ...changes, area, recovered: false }
    window.history.pushState({}, '', routeHref(next))
    setRoute(next)
    if ((changes.experimentId !== undefined && changes.experimentId !== route.experimentId)
      || (changes.projectId !== undefined && changes.projectId !== route.projectId)) setFrozenAt(null)
    if (area !== 'execute') setPreflightReport(null)
    window.requestAnimationFrame(() => document.getElementById('workbench-main')?.focus())
  }, [route])
  const chooseProject = useCallback((projectId: string) => navigate(route.area, {
    projectId,
    pack: null,
    experimentId: null,
    executionId: null,
    reportDigest: null,
    leftAttemptId: null,
    rightAttemptId: null,
    sourceDigest: null,
    xrayDigest: null,
    attemptIds: [],
  }), [navigate, route.area])

  const evidence = useMemo(() => <div className="sa-inspector-stack">
    <WorkbenchPanel title={mode === 'lab' ? 'Selected durable identifiers' : 'Selected protocol context'} action={<StatusIndicator tone="info">URL-owned</StatusIndicator>}>
      {mode === 'lab'
        ? <dl className="sa-inspector-list"><div><dt>Project</dt><dd><code>{route.projectId ?? 'Not selected'}</code></dd></div><div><dt>StudyPack</dt><dd><code>{route.pack ? `${route.pack.studyPackId}@${route.pack.version}` : 'Not selected'}</code></dd></div><div><dt>Experiment</dt><dd><code>{route.experimentId ?? 'Not selected'}</code></dd></div><div><dt>Execution</dt><dd><code>{route.executionId ?? 'Not selected'}</code></dd></div><div><dt>Report</dt><dd><code>{route.reportDigest ?? 'Not selected'}</code></dd></div></dl>
        : <dl className="sa-inspector-list"><div><dt>Study</dt><dd>{route.pack ? 'Selected' : 'Not selected'}</dd></div><div><dt>Comparison design</dt><dd>{route.experimentId ? 'Selected' : 'Not selected'}</dd></div><div><dt>Run</dt><dd>{route.executionId ? 'Selected' : 'Not selected'}</dd></div><div><dt>Evidence report</dt><dd>{route.reportDigest ? 'Selected' : 'Not selected'}</dd></div></dl>}
    </WorkbenchPanel>
    <WorkbenchPanel title="Runtime revision" action={<StatusIndicator tone={revision.tone}>{revision.label}</StatusIndicator>}>
      <p className="sa-journey-copy">{revision.message}</p>
      {mode === 'lab' && <dl className="sa-inspector-list"><div><dt>Frontend</dt><dd><code>{revision.frontendSha}</code></dd></div><div><dt>Backend</dt><dd><code>{revision.backendSha ?? 'Unavailable'}</code></dd></div></dl>}
      <DisclosureRow title="What revision verification means">A matching complete Git identity establishes frontend/backend deployment coherence only. It does not establish scientific validity, correct configuration, or independent reproduction.</DisclosureRow>
    </WorkbenchPanel>
    <WorkbenchPanel title="Claim boundary"><p className="sa-journey-copy">This inspector links only selected durable context. It does not infer artifacts, outcomes, costs, evidence class, independent reproduction, or claim maturity.</p><DisclosureRow title="Evidence limitation">Integrity and custody are not outcome correctness or independent validation. Unknown values remain unknown.</DisclosureRow></WorkbenchPanel>
  </div>, [mode, revision, route])

  const surface = (() => {
    if (sessionState === 'loading') return <WorkbenchState kind="loading" title="Recovering session">Checking personal-mode authority or the configured team session before reading project data.</WorkbenchState>
    if (sessionState === 'error') return <WorkbenchState kind="error" title="Session recovery failed">{sessionMessage}</WorkbenchState>
    if (teamProject.kind === 'choose') return <ProjectChooser memberships={teamProject.memberships} mode={mode} onChoose={chooseProject} />
    const common = { client: arenaV1, projectId: route.projectId }
    switch (route.area) {
      case 'compare': return <DecisionCanvas job="compare" hasStudy={Boolean(route.pack)} hasExperiment={Boolean(route.experimentId)} hasExecution={Boolean(route.executionId)} onNavigate={(area) => navigate(area)} />
      case 'diagnose': return <DecisionCanvas job="diagnose" hasStudy={Boolean(route.pack)} hasExperiment={Boolean(route.experimentId)} hasExecution={Boolean(route.executionId)} onNavigate={(area) => navigate(area)} />
      case 'improve': return <DecisionCanvas job="improve" hasStudy={Boolean(route.pack)} hasExperiment={Boolean(route.experimentId)} hasExecution={Boolean(route.executionId)} onNavigate={(area) => navigate(area)} />
      case 'prove': return <DecisionCanvas job="prove" hasStudy={Boolean(route.pack)} hasExperiment={Boolean(route.experimentId)} hasExecution={Boolean(route.executionId)} onNavigate={(area) => navigate(area)} />
      case 'studies': return <StudiesSurface {...common} mode={mode} selection={route.pack} onSelect={(pack) => navigate('design', { pack, experimentId: null, executionId: null, reportDigest: null })} />
      case 'design': return <DesignSurface {...common} packSelection={route.pack} experimentId={route.experimentId} mode={mode} onExperimentSelected={(experimentId) => navigate('preflight', { experimentId, executionId: null, reportDigest: null })} onNavigateToStudies={() => navigate('studies')} />
      case 'preflight': return <PreflightSurface {...common} mode={mode} experimentId={route.experimentId} isFixture={fixturePack(route.pack ? { study_pack_id: route.pack.studyPackId } : null)} onNavigateToDesign={() => navigate('design')} onPreflightReport={setPreflightReport} onExperimentIdentity={updateExperimentIdentity} onProceedToExecute={() => navigate('execute')} />
      case 'execute': return <ExecuteSurface {...common} frozenExperimentId={route.experimentId} preflightReport={preflightReport} mode={mode} requestedExecutionId={route.executionId} isBundledOfflineDemo={route.pack?.studyPackId === 'offline-demo-v1'} onExecutionSelected={(executionId) => navigate('execute', { executionId })} onNavigateToAnalyze={(executionId) => navigate('analyze', { executionId })} onNavigateToPreflight={() => navigate('preflight')} onSwitchToLab={() => setMode('lab')} />
      case 'analyze': return <AnalyzeSurface {...common} mode={mode} experimentId={route.experimentId} executionId={route.executionId} initialReportDigest={route.reportDigest} onReportSelected={(reportDigest) => navigate('analyze', { reportDigest })} onNavigateToExecute={() => navigate('execute')} onNavigateToDesign={() => navigate('design')} />
      case 'xray': return <Suspense fallback={<DeferredSurfaceFallback title="Harness X-Ray" />}><XRaySurface {...common} mode={mode} sourceDigest={route.sourceDigest} /></Suspense>
      case 'observatory': return <Suspense fallback={<DeferredSurfaceFallback title="Observatory" />}><ObservatorySurface {...common} mode={mode} attemptIds={route.attemptIds} sourceDigest={route.sourceDigest} xrayDigest={route.xrayDigest} /></Suspense>
      case 'counterfactual': return <Suspense fallback={<DeferredSurfaceFallback title="Counterfactual Replay" />}><CounterfactualSurface {...common} mode={mode} /></Suspense>
      case 'forge': return <Suspense fallback={<DeferredSurfaceFallback title="Arena Forge" />}><ForgeSurface {...common} mode={mode} /></Suspense>
      case 'trace-lab': return <Suspense fallback={<DeferredSurfaceFallback title="Trace internals" />}><TraceLabSurface {...common} mode={mode} executionId={route.executionId} initialLeftAttemptId={route.leftAttemptId} initialRightAttemptId={route.rightAttemptId} onAttemptPairSelected={(leftAttemptId, rightAttemptId) => navigate('trace-lab', { leftAttemptId, rightAttemptId })} /></Suspense>
      case 'review': return <ReviewSurface {...common} mode={mode} />
      case 'evidence': return <EvidenceSurface {...common} mode={mode} executionId={route.executionId} reportDigest={route.reportDigest} />
      case 'settings': return <SettingsSurface {...common} mode={mode} onProjectSelect={chooseProject} />
    }
  })()

  const isFrozen = Boolean(route.experimentId && frozenAt)
  const specTitle = route.experimentId ? isFrozen ? 'Frozen spec' : 'Experiment' : 'Frozen spec'
  const specLabel = route.experimentId ? isFrozen ? route.experimentId : `Unfrozen spec ${route.experimentId}` : 'No frozen specification'

  return <WorkbenchShell activeArea={route.area} onNavigate={(area) => navigate(area)} mode={mode} onModeChange={setMode} studyLabel={route.pack ? mode === 'lab' ? `${route.pack.studyPackId} @ ${route.pack.version}` : 'Study selected' : 'No study selected'} specTitle={specTitle} specLabel={route.experimentId ? mode === 'lab' ? specLabel : isFrozen ? 'Frozen comparison selected' : 'Comparison selected' : 'No frozen specification'} statuses={[{ label: 'Execution', value: route.executionId ? mode === 'lab' ? route.executionId : 'Run selected' : 'Not selected', tone: route.executionId ? 'info' : 'warning' }, { label: 'Revision', value: revision.label, tone: revision.tone }]} stageTitle={route.area === 'studies' ? 'Study Canvas' : undefined} evidence={evidence}>
    {route.recovered && <p className="sa-journey-note" role="status">Unknown Workbench route recovered to Compare. Durable selections were preserved only when present in the URL.</p>}
    {surface}
  </WorkbenchShell>
}

function DeferredSurfaceFallback({ title }: { title: string }) {
  return <WorkbenchState kind="loading" title={`Loading ${title}`}>Loading this optional analysis surface.</WorkbenchState>
}

function ProjectChooser({ memberships, mode, onChoose }: { memberships: NonNullable<ArenaSession['memberships']>; mode: 'guided' | 'lab'; onChoose: (projectId: string) => void }) {
  if (memberships.length === 0) return <WorkbenchState kind="empty" title="No project membership">This authenticated team session has no project membership. An administrator must grant one before project-scoped work can be recovered.</WorkbenchState>
  return <WorkbenchPanel title="Choose a project" action={<StatusIndicator tone="warning">Project required</StatusIndicator>}><p className="sa-journey-copy">Team mode does not infer a project from browser state. Choose one authorized membership; the selected durable project context will be written to the URL.</p><ul className="sa-journey-list">{memberships.map((membership, index) => <li key={membership.project_id}>{mode === 'lab' ? <code>{membership.project_id}</code> : `Authorized project ${index + 1}`} — {membership.role} <WorkbenchButton tone="primary" onClick={() => onChoose(membership.project_id)}>Use project</WorkbenchButton></li>)}</ul></WorkbenchPanel>
}
