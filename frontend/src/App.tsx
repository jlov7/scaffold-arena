import {
  useState,
  useEffect,
  useCallback,
  useRef,
  useMemo,
} from 'react'
import {
  fetchMeta,
  createComparison,
  createModelComparison,
  fetchRuns,
  fetchRunDetails,
  fetchStats,
  runAutopsy,
  createPatchRerun,
  generateReport,
  getLlmApiKey,
  setLlmApiKey,
} from './api/client'
import { useArenaRun } from './hooks/useArenaRun'
import { useOnlineStatus } from './hooks/useOnlineStatus'
import { useReducedMotion } from './hooks/useReducedMotion'
import { useSSE } from './hooks/useSSE'
import { TaskSelector } from './components/TaskSelector'
import AutopsyModal from './components/AutopsyModal'
import ReportModal from './components/ReportModal'
import LoadingSkeletons from './components/LoadingSkeletons'
import ToastStack, { type ToastItem } from './components/ToastStack'
import ShortcutOverlay from './components/ShortcutOverlay'
import LiveRegion from './components/LiveRegion'
import GuidedTourModal from './components/GuidedTourModal'
import { AppFooter } from './components/shell/AppFooter'
import { AppShellHeader } from './components/shell/AppShellHeader'
import { MobileNextActionBar } from './components/shell/MobileNextActionBar'
import HelpCenterModal from './components/help/HelpCenterModal'
import {
  getTaskPlaybook,
  resolveHelpBlocker,
  type PlaybookAction,
} from './features/help/playbook'
import { COPY } from './content/copy'
import {
  type AppView,
} from './app/viewState'
import { useViewNavigation } from './features/shell/useViewNavigation'
import { useJourneyProgress } from './features/journey/useJourneyProgress'
import {
  buildNextActionCopy,
  resolveNextActionKey,
  type NextActionKey,
} from './features/journey/nextAction'
import { ProgressStepper } from './components/journey/ProgressStepper'
import { WorkspaceSection } from './components/layout/WorkspaceSection'
import {
  ExperienceModeCard,
  type ExperienceMode,
  type UserProfile,
} from './components/journey/ExperienceModeCard'
import { classifyApiError, remediationForErrorKind } from './errors/classify'
import {
  getTelemetryConsent,
  readTrackedEvents,
  setTelemetryConsent,
  trackEvent,
} from './telemetry/tracker'
import {
  parseRunDetailsResponse,
  parseRunListResponse,
  type ParsedRunRecord,
} from './lib/schema'
import { getFeatureFlag } from './experiments/flags'
import { assignVariant } from './experiments/assign'
import { describeResultsWorkspaceState } from './features/states/taxonomy'
import {
  readBooleanFlag,
  readCompactMode,
  readOnboardingProgress,
  type OnboardingProgressState,
} from './features/app/persistence'
import {
  buildRoleResultsSummary,
  type RoleResultsSummary,
} from './features/results/roleSummary'
import { executeNextActionCommand } from './features/commands/appCommands'
import { ArenaWorkspace } from './features/workspaces/ArenaWorkspace'
import { HistoryWorkspace } from './features/workspaces/HistoryWorkspace'
import { LeaderboardWorkspace } from './features/workspaces/LeaderboardWorkspace'
import { ResultsWorkspace } from './features/workspaces/ResultsWorkspace'
import { SettingsWorkspace } from './features/workspaces/SettingsWorkspace'
import type {
  AppMeta,
  AutopsyResult,
  LeaderboardStats,
  RunMetrics,
  RunResults,
} from './types'

interface ComparisonCaseDisplay {
  case_id: string
  label: string
  model_id: string
  scaffold_id: string
  score: number
  cost: number
  metrics?: RunMetrics
}

interface CustomTaskDef {
  id: string
  name: string
  prompt: string
  schemaText: string
}

type ArenaWorkspaceLane = 'onboarding' | 'configure' | 'live'
type ResultsWorkspaceLane = 'summary' | 'diagnostics'

interface PersonaGuidance {
  lane: ArenaWorkspaceLane
  title: string
  body: string
  cta: string
}

type RunHistoryRecord = ParsedRunRecord

function caseLabel(caseId: string): string {
  switch (caseId) {
    case 'cheap_winning':
      return 'Cheap Model + Winner'
    case 'expensive_bare':
      return 'Expensive + Bare'
    case 'expensive_winning':
      return 'Expensive + Winner'
    case 'model_a':
      return 'Model A'
    case 'model_b':
      return 'Model B'
    default:
      return caseId
  }
}

const CASE_ORDER = [
  'cheap_winning',
  'expensive_bare',
  'expensive_winning',
  'model_a',
  'model_b',
]

function getErrorMessage(err: unknown): string {
  const raw =
    err instanceof Error && err.message
      ? err.message
      : 'Unexpected request failure.'
  const classified = classifyApiError(raw)
  return `${raw} ${remediationForErrorKind(classified.kind)}`
}

const TASK_STORAGE_KEY = 'scaffold_arena_selected_task'
const MODEL_STORAGE_KEY = 'scaffold_arena_selected_model'
const OPTIONS_STORAGE_KEY = 'scaffold_arena_run_options'
const CUSTOM_TASKS_STORAGE_KEY = 'scaffold_arena_custom_tasks'
const CACHE_STORAGE_KEY = 'scaffold_arena_result_cache'
const THEME_STORAGE_KEY = 'scaffold_arena_theme'
const TOUR_STORAGE_KEY = 'scaffold_arena_tour_seen'
const API_TOKEN_STORAGE_KEY = 'scaffold_arena_api_token'
const CONTEXT_STORAGE_KEY = 'scaffold_arena_last_context'
const EXPERIENCE_MODE_STORAGE_KEY = 'scaffold_arena_experience_mode'
const PROFILE_STORAGE_KEY = 'scaffold_arena_user_profile'
const ONBOARDING_PROGRESS_STORAGE_KEY = 'scaffold_arena_onboarding_progress'
const CHECKLIST_HIDDEN_STORAGE_KEY = 'scaffold_arena_checklist_hidden'
const AUTOPSY_GUIDE_DISMISSED_KEY = 'scaffold_arena_autopsy_guide_dismissed'
const COMPACT_MODE_STORAGE_KEY = 'scaffold_arena_compact_mode'
const CACHE_TTL_MS = (() => {
  const raw = Number(import.meta.env.VITE_RESULT_CACHE_TTL_HOURS ?? 24)
  if (!Number.isFinite(raw) || raw <= 0) return 24 * 60 * 60 * 1000
  return raw * 60 * 60 * 1000
})()
const TOUR_STEPS = [
  {
    targetId: 'tour-task-selector',
    title: 'Pick your task',
    body: 'Select a task and model to benchmark scaffold behavior.',
  },
  {
    targetId: 'tour-settings-link',
    title: 'Tune run settings',
    body: 'Adjust temperature, token limits, and comparison mode before running.',
  },
  {
    targetId: 'arena-grid',
    title: 'Compare and diagnose',
    body: 'Review scores, diffs, history, and autopsy guidance to improve outcomes.',
  },
]

const PROFILE_AUDIENCE_LABEL: Record<UserProfile, string> = {
  evaluator: 'Evaluator',
  operator: 'Operator',
  analyst: 'Analyst',
  executive: 'Executive',
}

const PERSONA_GUIDANCE: Record<UserProfile, PersonaGuidance> = {
  evaluator: {
    lane: 'configure',
    title: 'Evaluator launch path',
    body: 'Run one benchmark fast, then compare score + cost before opening diagnostics.',
    cta: 'Go to configure lane',
  },
  operator: {
    lane: 'configure',
    title: 'Operator launch path',
    body: 'Set task/model, check operational guardrails, run, then verify fallback and retries.',
    cta: 'Configure with guardrails',
  },
  analyst: {
    lane: 'live',
    title: 'Analyst launch path',
    body: 'Start run, then move to diagnostics lane to inspect diff + autopsy evidence.',
    cta: 'Open live run lane',
  },
  executive: {
    lane: 'configure',
    title: 'Executive launch path',
    body: 'Use the shortest path: run once, open Results summary, then export report.',
    cta: 'Start quick decision path',
  },
}

function isTypingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false
  const tag = target.tagName.toLowerCase()
  return (
    tag === 'input' ||
    tag === 'textarea' ||
    tag === 'select' ||
    target.isContentEditable
  )
}

function readResultCache(): Record<string, unknown> {
  try {
    const raw = localStorage.getItem(CACHE_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

function writeResultCache(cache: Record<string, unknown>): void {
  try {
    localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache))
  } catch {
    // localStorage unavailable
  }
}

function hasConfiguredApiToken(): boolean {
  try {
    const token = localStorage.getItem(API_TOKEN_STORAGE_KEY)
    return Boolean(token && token.trim().length > 0)
  } catch {
    return false
  }
}

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
  const scaffoldNames = useMemo(
    () => Object.fromEntries(scaffolds.map((s) => [s.id, s.name])),
    [scaffolds],
  )
  const [selectedTaskId, setSelectedTaskId] = useState('')
  const [selectedModelId, setSelectedModelId] = useState('')
  const isOnline = useOnlineStatus()
  const prefersReducedMotion = useReducedMotion()
  const enableModelMode = getFeatureFlag('enable_model_mode')
  const tourEntryVariant = useMemo(
    () => assignVariant('tour_entry', ['auto_open', 'cta_only'] as const),
    [],
  )
  const postRunRailVariant = useMemo(
    () =>
      assignVariant('post_run_rail_order', ['compare_first', 'export_first'] as const),
    [],
  )
  const personaPathVariant = useMemo(
    () =>
      assignVariant('persona_path', [
        'evaluator_default',
        'operator_default',
      ] as const),
    [],
  )

  // --- Arena run ---
  const {
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
    setPanels,
  } = useArenaRun(scaffolds)
  const [operationError, setOperationError] = useState<string | null>(null)
  const [shortcutsOpen, setShortcutsOpen] = useState(false)
  const [toasts, setToasts] = useState<ToastItem[]>([])
  const [helpSource, setHelpSource] = useState<
    'header' | 'banner' | 'keyboard' | 'card' | 'route' | 'unknown'
  >('unknown')
  const [helpOpen, setHelpOpen] = useState(false)
  const [safeFallbackMode, setSafeFallbackMode] = useState(false)
  const [showFrictionFeedback, setShowFrictionFeedback] = useState(false)
  const [runMode, setRunMode] = useState<'scaffold' | 'model'>('scaffold')
  const [modelModeScaffoldId, setModelModeScaffoldId] = useState('bare')
  const [secondaryModelId, setSecondaryModelId] = useState('')
  const [forceRerun, setForceRerun] = useState(false)
  const [runOptions, setRunOptions] = useState({
    temperature: 0,
    max_output_tokens: 2048,
    timeout_s: 75,
  })
  const [customTasks, setCustomTasks] = useState<CustomTaskDef[]>([])
  const [customTaskName, setCustomTaskName] = useState('')
  const [customTaskPrompt, setCustomTaskPrompt] = useState('')
  const [customTaskSchemaText, setCustomTaskSchemaText] = useState('')
  const [runHistory, setRunHistory] = useState<RunHistoryRecord[]>([])
  const [historyHydrationPending, setHistoryHydrationPending] = useState(false)
  const [leaderboardStats, setLeaderboardStats] = useState<LeaderboardStats | null>(null)
  const [theme, setTheme] = useState<'dark' | 'light'>('dark')
  const [experienceMode, setExperienceMode] = useState<ExperienceMode>('guided')
  const [userProfile, setUserProfile] = useState<UserProfile>('evaluator')
  const [onboardingProgress, setOnboardingProgress] = useState<OnboardingProgressState>(() =>
    readOnboardingProgress(ONBOARDING_PROGRESS_STORAGE_KEY),
  )
  const [checklistHidden, setChecklistHidden] = useState<boolean>(() =>
    readBooleanFlag(CHECKLIST_HIDDEN_STORAGE_KEY),
  )
  const [autopsyGuideDismissed, setAutopsyGuideDismissed] = useState<boolean>(() =>
    readBooleanFlag(AUTOPSY_GUIDE_DISMISSED_KEY),
  )
  const [compactMode, setCompactMode] = useState<boolean>(() =>
    readCompactMode(COMPACT_MODE_STORAGE_KEY),
  )
  const [deferredResultsReady, setDeferredResultsReady] = useState(false)
  const [telemetryConsent, setTelemetryConsentState] = useState(false)
  const [telemetryEvents, setTelemetryEvents] = useState(() => readTrackedEvents())
  const [notificationPermission, setNotificationPermissionState] = useState<
    NotificationPermission | 'unsupported'
  >(() =>
    'Notification' in window ? Notification.permission : 'unsupported',
  )
  const [llmApiKey, setLlmApiKeyState] = useState(() => getLlmApiKey() ?? '')
  const [showLlmKey, setShowLlmKey] = useState(false)
  const [tourOpen, setTourOpen] = useState(false)
  const [tourStep, setTourStep] = useState(0)
  const { activeView, navigateToView } = useViewNavigation()
  const [arenaLane, setArenaLane] = useState<ArenaWorkspaceLane>('onboarding')
  const [resultsLane, setResultsLane] = useState<ResultsWorkspaceLane>('summary')
  const [liveAnnouncement, setLiveAnnouncement] = useState<{
    message: string
    priority: 'polite' | 'assertive'
  } | null>(null)
  const notificationPromptedRef = useRef(false)
  const lastTrackedRunCompleteRef = useRef<string | null>(null)
  const onboardingStepsTrackedRef = useRef({
    task: false,
    model: false,
    run: false,
    review: false,
    comparison: false,
  })
  const blockerTrackedRef = useRef<string | null>(null)
  const activationTrackedRef = useRef(false)
  const activeBlockerRef = useRef<{ blocker: string; startedAt: number } | null>(
    null,
  )
  const navHistoryRef = useRef<Array<{ view: AppView; ts: number }>>([])
  const navSignalRef = useRef<string | null>(null)
  const routeTimingRef = useRef<{ view: AppView; enteredAt: number } | null>(null)
  const taskOptions = useMemo(
    () => [
      ...tasks,
      ...customTasks.map((task) => ({
        id: task.id,
        name: task.name,
        subtitle: 'Custom task',
        type: 'custom',
      })),
    ],
    [customTasks, tasks],
  )

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

  const pushToast = useCallback(
    (type: ToastItem['type'], message: string) => {
      const id = Date.now() + Math.floor(Math.random() * 1000)
      setToasts((prev) => [...prev, { id, type, message }])
    },
    [],
  )

  const dismissToast = useCallback((id: number) => {
    setToasts((prev) => prev.filter((toast) => toast.id !== id))
  }, [])

  useEffect(() => {
    if (runError) {
      pushToast('error', runError)
    }
  }, [runError, pushToast])

  useEffect(() => {
    if (isRunning) {
      setLiveAnnouncement({
        message: 'Arena run started. Scaffolds are now processing.',
        priority: 'polite',
      })
    }
  }, [isRunning])

  useEffect(() => {
    if (connectionState === 'retrying') {
      setLiveAnnouncement({
        message: `Connection lost. Retrying stream connection, attempt ${connectionRetryCount}.`,
        priority: 'assertive',
      })
    } else if (connectionState === 'failed') {
      setLiveAnnouncement({
        message: 'Connection failed. Please retry the stream.',
        priority: 'assertive',
      })
    }
  }, [connectionRetryCount, connectionState])

  useEffect(() => {
    if (!finalResults || isRunning) return
    const winnerLabel = winnerId ? scaffoldNames[winnerId] ?? winnerId : 'No winner'
    setLiveAnnouncement({
      message: `Run complete. Winner: ${winnerLabel}.`,
      priority: 'polite',
    })
  }, [finalResults, isRunning, scaffoldNames, winnerId])

  useEffect(() => {
    const errorMessage = runError ?? operationError
    if (!errorMessage) return
    setLiveAnnouncement({
      message: errorMessage,
      priority: 'assertive',
    })
  }, [operationError, runError])

  useEffect(() => {
    const handler = (event: Event) => {
      const custom = event as CustomEvent<{ type: ToastItem['type']; message: string }>
      if (!custom.detail) return
      pushToast(custom.detail.type, custom.detail.message)
    }
    window.addEventListener('app-toast', handler)
    return () => window.removeEventListener('app-toast', handler)
  }, [pushToast])

  const refreshRunHistory = useCallback(async () => {
    try {
      const res = await fetchRuns(100)
      const runs = parseRunListResponse(res).runs.slice()
      runs.sort((a, b) => {
        const aTs = Number(a.completed_at ?? a.created_at ?? 0)
        const bTs = Number(b.completed_at ?? b.created_at ?? 0)
        return bTs - aTs
      })
      setRunHistory(runs)
    } catch (err) {
      pushToast('error', `Failed to load run history: ${getErrorMessage(err)}`)
    }
  }, [pushToast])

  const refreshLeaderboardStats = useCallback(async () => {
    try {
      const stats = await fetchStats(2000)
      setLeaderboardStats(stats)
    } catch {
      setLeaderboardStats(null)
    }
  }, [])

  useEffect(() => {
    try {
      const rawOptions = localStorage.getItem(OPTIONS_STORAGE_KEY)
      if (rawOptions) {
        const parsed = JSON.parse(rawOptions) as typeof runOptions
        if (typeof parsed === 'object' && parsed) {
          setRunOptions(parsed)
        }
      }
      const rawCustom = localStorage.getItem(CUSTOM_TASKS_STORAGE_KEY)
      if (rawCustom) {
        const parsed = JSON.parse(rawCustom) as CustomTaskDef[]
        if (Array.isArray(parsed)) setCustomTasks(parsed)
      }
      const storedTheme = localStorage.getItem(THEME_STORAGE_KEY)
      if (storedTheme === 'dark' || storedTheme === 'light') {
        setTheme(storedTheme)
      } else {
        const systemDark = window.matchMedia('(prefers-color-scheme: dark)').matches
        setTheme(systemDark ? 'dark' : 'light')
      }
      const storedMode = localStorage.getItem(EXPERIENCE_MODE_STORAGE_KEY)
      if (storedMode === 'guided' || storedMode === 'advanced') {
        setExperienceMode(storedMode)
      } else if (personaPathVariant === 'operator_default') {
        setExperienceMode('advanced')
      }
      const storedProfile = localStorage.getItem(PROFILE_STORAGE_KEY)
      if (
        storedProfile === 'evaluator' ||
        storedProfile === 'operator' ||
        storedProfile === 'analyst' ||
        storedProfile === 'executive'
      ) {
        setUserProfile(storedProfile)
      } else {
        setUserProfile(
          personaPathVariant === 'operator_default' ? 'operator' : 'evaluator',
        )
      }
      setTelemetryConsentState(getTelemetryConsent())
      if (
        tourEntryVariant === 'auto_open' &&
        !localStorage.getItem(TOUR_STORAGE_KEY)
      ) {
        setTourOpen(true)
      }
    } catch {
      // localStorage unavailable
    }
  }, [personaPathVariant, tourEntryVariant])

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme)
    try {
      localStorage.setItem(THEME_STORAGE_KEY, theme)
    } catch {
      // localStorage unavailable
    }
  }, [theme])

  useEffect(() => {
    try {
      localStorage.setItem(COMPACT_MODE_STORAGE_KEY, compactMode ? '1' : '0')
    } catch {
      // localStorage unavailable
    }
  }, [compactMode])

  useEffect(() => {
    try {
      localStorage.setItem(EXPERIENCE_MODE_STORAGE_KEY, experienceMode)
      localStorage.setItem(PROFILE_STORAGE_KEY, userProfile)
    } catch {
      // localStorage unavailable
    }
  }, [experienceMode, userProfile])

  useEffect(() => {
    trackEvent('persona_selected', {
      profile: userProfile,
      experience_mode: experienceMode,
    })
  }, [experienceMode, userProfile])

  useEffect(() => {
    try {
      localStorage.setItem(
        ONBOARDING_PROGRESS_STORAGE_KEY,
        JSON.stringify(onboardingProgress),
      )
      if (checklistHidden) {
        localStorage.setItem(CHECKLIST_HIDDEN_STORAGE_KEY, '1')
      } else {
        localStorage.removeItem(CHECKLIST_HIDDEN_STORAGE_KEY)
      }
      if (autopsyGuideDismissed) {
        localStorage.setItem(AUTOPSY_GUIDE_DISMISSED_KEY, '1')
      } else {
        localStorage.removeItem(AUTOPSY_GUIDE_DISMISSED_KEY)
      }
    } catch {
      // localStorage unavailable
    }
  }, [autopsyGuideDismissed, checklistHidden, onboardingProgress])

  useEffect(() => {
    setTelemetryConsent(telemetryConsent)
  }, [telemetryConsent])

  useEffect(() => {
    if (activeView !== 'settings') return
    setTelemetryEvents(readTrackedEvents())
    const timer = window.setInterval(() => {
      setTelemetryEvents(readTrackedEvents())
    }, 2000)
    return () => window.clearInterval(timer)
  }, [activeView])

  useEffect(() => {
    setNotificationPermissionState(
      'Notification' in window ? Notification.permission : 'unsupported',
    )
  }, [])

  const requestNotificationPermission = useCallback(() => {
    if (!('Notification' in window)) {
      setNotificationPermissionState('unsupported')
      return
    }
    void Notification.requestPermission().then((permission) => {
      setNotificationPermissionState(permission)
    })
  }, [])

  useEffect(() => {
    const now = Date.now()
    if (routeTimingRef.current) {
      trackEvent('route_timing', {
        from_view: routeTimingRef.current.view,
        to_view: activeView,
        dwell_ms: now - routeTimingRef.current.enteredAt,
      })
    }
    routeTimingRef.current = { view: activeView, enteredAt: now }

    trackEvent('route_changed', { view: activeView })
    const history = [...navHistoryRef.current, { view: activeView, ts: now }].slice(-6)
    navHistoryRef.current = history
    if (history.length < 4) return

    const a = history[history.length - 4]
    const b = history[history.length - 3]
    const c = history[history.length - 2]
    const d = history[history.length - 1]
    const isPogo =
      a.view === c.view &&
      b.view === d.view &&
      a.view !== b.view &&
      d.ts - a.ts <= 10_000

    if (!isPogo) return
    const signalKey = `${a.view}:${b.view}:${d.ts - a.ts}`
    if (navSignalRef.current === signalKey) return
    navSignalRef.current = signalKey
    trackEvent('nav_confusion_signal', {
      pattern: 'pogo_thrash',
      view_a: a.view,
      view_b: b.view,
      window_ms: d.ts - a.ts,
    })
  }, [activeView])

  useEffect(() => {
    trackEvent('experiment_exposed', {
      experiment: 'tour_entry',
      variant: tourEntryVariant,
    })
    trackEvent('experiment_exposed', {
      experiment: 'post_run_rail_order',
      variant: postRunRailVariant,
    })
    trackEvent('experiment_exposed', {
      experiment: 'persona_path',
      variant: personaPathVariant,
    })
  }, [personaPathVariant, postRunRailVariant, tourEntryVariant])

  useEffect(() => {
    if (!enableModelMode && runMode === 'model') {
      setRunMode('scaffold')
    }
  }, [enableModelMode, runMode])

  useEffect(() => {
    if (!tourOpen) return
    const step = TOUR_STEPS[tourStep]
    if (!step) return
    const target = document.getElementById(step.targetId)
    if (!target) return
    target.classList.add('tour-highlight')
    target.scrollIntoView({
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
      block: 'center',
    })
    return () => {
      target.classList.remove('tour-highlight')
    }
  }, [tourOpen, tourStep, prefersReducedMotion])

  useEffect(() => {
    if (!meta) return

    const params = new URLSearchParams(window.location.search)
    const taskFromUrl = params.get('task')
    const modelFromUrl = params.get('model')

    let taskFromStorage: string | null = null
    let modelFromStorage: string | null = null
    try {
      taskFromStorage = localStorage.getItem(TASK_STORAGE_KEY)
      modelFromStorage = localStorage.getItem(MODEL_STORAGE_KEY)
    } catch {
      // localStorage unavailable
    }

    const validTaskIds = new Set(tasks.map((t) => t.id))
    const validModelIds = new Set(models.map((m) => m.id))

    const nextTask =
      (taskFromUrl && validTaskIds.has(taskFromUrl) && taskFromUrl) ||
      (taskFromStorage && validTaskIds.has(taskFromStorage) && taskFromStorage) ||
      tasks[0]?.id ||
      ''

    const nextModel =
      (modelFromUrl && validModelIds.has(modelFromUrl) && modelFromUrl) ||
      (modelFromStorage && validModelIds.has(modelFromStorage) && modelFromStorage) ||
      models[0]?.id ||
      ''

    setSelectedTaskId(nextTask)
    setSelectedModelId(nextModel)
    if (!secondaryModelId) {
      setSecondaryModelId(models[1]?.id ?? nextModel)
    }
    if (!modelModeScaffoldId) {
      setModelModeScaffoldId(scaffolds[0]?.id ?? 'bare')
    }
  }, [meta, modelModeScaffoldId, models, scaffolds, secondaryModelId, tasks])

  useEffect(() => {
    if (!selectedTaskId || !selectedModelId) return
    try {
      localStorage.setItem(TASK_STORAGE_KEY, selectedTaskId)
      localStorage.setItem(MODEL_STORAGE_KEY, selectedModelId)
    } catch {
      // localStorage unavailable
    }

    const params = new URLSearchParams(window.location.search)
    params.set('task', selectedTaskId)
    params.set('model', selectedModelId)
    const nextUrl = `${window.location.pathname}?${params.toString()}`
    window.history.replaceState({}, '', nextUrl)
  }, [selectedTaskId, selectedModelId])

  useEffect(() => {
    try {
      localStorage.setItem(OPTIONS_STORAGE_KEY, JSON.stringify(runOptions))
      localStorage.setItem(CUSTOM_TASKS_STORAGE_KEY, JSON.stringify(customTasks))
    } catch {
      // localStorage unavailable
    }
  }, [customTasks, runOptions])

  // Track last run params for comparison/report
  const lastRunRef = useRef({ taskId: '', modelId: '' })
  const [hasEverRun, setHasEverRun] = useState(false)

  useEffect(() => {
    if (activeView !== 'arena') return

    if (isRunning) {
      setArenaLane('live')
      return
    }

    if (!hasEverRun && !finalResults) {
      setArenaLane('onboarding')
      return
    }

    setArenaLane((current) => (current === 'onboarding' ? 'configure' : current))
  }, [activeView, finalResults, hasEverRun, isRunning])

  useEffect(() => {
    if (activeView !== 'results') return
    setResultsLane('summary')
  }, [activeView, runId])

  const estimatedCostUsd = useMemo(() => {
    if (!selectedTaskId || !selectedModelId) return null
    const model = models.find((m) => m.id === selectedModelId)
    if (!model) return null

    const estimates: Record<string, { input: number; output: number }> = {
      extraction: { input: 6500, output: 2200 },
      risk: { input: 8500, output: 2800 },
      research: { input: 12000, output: 4500 },
    }
    const taskEstimate = estimates[selectedTaskId] ?? { input: 8000, output: 3000 }
    const scaffoldCount = Math.max(1, scaffolds.length || 4)

    const perCall =
      (taskEstimate.input / 1_000_000) * model.input_usd_per_mtok +
      (taskEstimate.output / 1_000_000) * model.output_usd_per_mtok
    return perCall * scaffoldCount
  }, [models, scaffolds.length, selectedModelId, selectedTaskId])

  const buildCacheKey = useCallback(
    (taskId: string, modelId: string) =>
      JSON.stringify({
        mode: runMode,
        taskId,
        modelId,
        scaffoldIds: scaffolds.map((s) => s.id),
        options: runOptions,
      }),
    [runMode, runOptions, scaffolds],
  )

  const handleRun = useCallback(
    (taskId: string, modelId: string) => {
      if (!isOnline) {
        const message = COPY.errors.offlineRunBlocked
        setOperationError(message)
        pushToast('error', message)
        return
      }
      trackEvent('run_started', {
        task_id: taskId,
        model_id: modelId,
        mode: runMode,
      })
      if (
        'Notification' in window &&
        Notification.permission === 'default' &&
        !notificationPromptedRef.current
      ) {
        notificationPromptedRef.current = true
        void Notification.requestPermission().catch(() => {
          // browser denied or blocked prompt
        })
      }

      lastRunRef.current = { taskId, modelId }
      setHasEverRun(true)
      setArenaLane('live')
      setOperationError(null)
      setComparisonCases([])
      setComparisonLoading(false)
      setComparisonStreamUrl(null)
      setAutopsyTarget(null)
      setAutopsyResult(null)
      if (runMode === 'model') {
        setComparisonLoading(true)
        void createModelComparison({
          task_id: taskId,
          model_a_id: modelId,
          model_b_id: secondaryModelId || modelId,
          scaffold_id: modelModeScaffoldId,
          options: runOptions,
        })
          .then((result) => {
            setComparisonStreamUrl(result.stream_url)
          })
          .catch((err) => {
            setComparisonLoading(false)
            const message = `Failed to start model comparison: ${getErrorMessage(err)}`
            setOperationError(message)
            pushToast('error', message)
          })
        return
      }

      const customTask = customTasks.find((task) => task.id === taskId)
      let customPayload: Record<string, unknown> | undefined
      if (customTask) {
        try {
          customPayload = {
            name: customTask.name,
            prompt: customTask.prompt,
            ...(customTask.schemaText.trim()
              ? { schema: JSON.parse(customTask.schemaText) }
              : {}),
          }
        } catch {
          const message = 'Custom task schema must be valid JSON.'
          setOperationError(message)
          pushToast('error', message)
          return
        }
      }

      if (!forceRerun) {
        const key = buildCacheKey(taskId, modelId)
        const cache = readResultCache()
        const cached = cache[key] as
          | { ts: number; results: RunResults; winnerId: string | null }
          | undefined
        if (cached && Date.now() - cached.ts < CACHE_TTL_MS) {
          hydrateFromResults(cached.results, cached.winnerId, { cached: true })
          pushToast('info', 'Loaded cached results')
          return
        }
      }

      void startRun(taskId, modelId, runOptions, customPayload).catch((err) => {
        const message = `Failed to start run: ${getErrorMessage(err)}`
        setOperationError(message)
        pushToast('error', message)
      })
    },
    [
      runMode,
      isOnline,
      secondaryModelId,
      modelModeScaffoldId,
      runOptions,
      customTasks,
      forceRerun,
      buildCacheKey,
      hydrateFromResults,
      pushToast,
      startRun,
    ],
  )

  const runFromCurrentSelection = useCallback(() => {
    if (!selectedTaskId || !selectedModelId || isRunning) return
    handleRun(selectedTaskId, selectedModelId)
  }, [handleRun, isRunning, selectedModelId, selectedTaskId])

  const openHelpCenter = useCallback(
    (source: 'header' | 'banner' | 'keyboard' | 'card' | 'route' | 'unknown') => {
      setHelpSource(source)
      setHelpOpen(true)
    },
    [],
  )

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setAutopsyTarget(null)
        setReportOpen(false)
        setShortcutsOpen(false)
        setHelpOpen(false)
        return
      }

      if (isTypingTarget(event.target)) return

      if ((event.metaKey || event.ctrlKey) && event.key === 'Enter') {
        event.preventDefault()
        runFromCurrentSelection()
        return
      }

      if (event.key === '?') {
        event.preventDefault()
        setShortcutsOpen((prev) => !prev)
        return
      }

      if (event.key === 'F1' || ((!event.metaKey && !event.ctrlKey && !event.altKey) && event.key.toLowerCase() === 'h')) {
        event.preventDefault()
        openHelpCenter('keyboard')
      }
    }

    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [openHelpCenter, runFromCurrentSelection])

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
          const comparisonRunId =
            typeof d.run_id === 'string' && d.run_id.length > 0 ? d.run_id : null
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
          trackEvent('comparison_completed', {
            run_id: comparisonRunId,
            cases: cases.length,
          })
          if (comparisonRunId) {
            const params = new URLSearchParams(window.location.search)
            params.set('run_id', comparisonRunId)
            window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
          }
          void refreshRunHistory()
          void refreshLeaderboardStats()
          break
        }
      }
    },
    [refreshLeaderboardStats, refreshRunHistory],
  )

  useSSE(comparisonStreamUrl, handleComparisonEvent, {
    onFailed: () => {
      setComparisonLoading(false)
      setComparisonStreamUrl(null)
      const message = 'Comparison stream connection failed.'
      setOperationError(message)
      pushToast('error', message)
    },
  })

  const handleRunComparison = useCallback(
    async (winningScaffoldId: string) => {
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
      } catch (err) {
        setComparisonLoading(false)
        const message = `Failed to run comparison: ${getErrorMessage(err)}`
        setOperationError(message)
        pushToast('error', message)
      }
    },
    [pushToast],
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

      setAutopsyGuideDismissed(true)
      const scaffoldName =
        scaffolds.find((s) => s.id === scaffoldId)?.name ?? scaffoldId
      setAutopsyTarget({ scaffoldId, scaffoldName })
      setAutopsyResult(null)
      setAutopsyLoading(true)
      setOperationError(null)
      trackEvent('autopsy_started', {
        scaffold_id: scaffoldId,
        task_id: lastRunRef.current.taskId,
      })

      try {
        const autopsy = await runAutopsy({
          task_id: lastRunRef.current.taskId,
          scaffold_id: scaffoldId,
          output: result.output,
          evaluation: result.evaluation as unknown as Record<string, unknown>,
          metrics: result.metrics as unknown as Record<string, unknown>,
        })
        setAutopsyResult(autopsy)
      } catch (err) {
        setAutopsyResult({
          failures: [],
          patch: {},
          summary: 'Failed to analyze.',
        })
        const message = `Autopsy failed: ${getErrorMessage(err)}`
        setOperationError(message)
        pushToast('error', message)
      } finally {
        setAutopsyLoading(false)
      }
    },
    [finalResults, pushToast, scaffolds],
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
      } catch (err) {
        const message = `Patch rerun failed: ${getErrorMessage(err)}`
        setOperationError(message)
        pushToast('error', message)
      }
    },
    [autopsyTarget, pushToast],
  )

  // --- Report ---
  const [hasExported, setHasExported] = useState(false)
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
    setOperationError(null)

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
      pushToast('success', 'Report generated')
      setHasExported(true)
      trackEvent('report_exported', {
        has_pdf: Boolean(report.pdf_base64),
      })
    } catch (err) {
      setReportMarkdown('# Error\n\nFailed to generate report.')
      const message = `Report generation failed: ${getErrorMessage(err)}`
      setOperationError(message)
      pushToast('error', message)
    } finally {
      setReportLoading(false)
    }
  }, [finalResults, comparisonCases, autopsyResult, pushToast])

  const handleExportJson = useCallback(() => {
    if (!finalResults) return
    const payload = {
      task_id: lastRunRef.current.taskId,
      model_id: lastRunRef.current.modelId,
      winner_id: winnerId,
      results: finalResults,
    }
    const timestamp = new Date().toISOString().replace(/[:.]/g, '-')
    const fileTask = (lastRunRef.current.taskId || 'task').replace(/[^a-zA-Z0-9_-]/g, '-')
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `scaffold-arena-${fileTask}-${timestamp}.json`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
    pushToast('success', 'JSON exported')
    trackEvent('json_exported', {
      task_id: lastRunRef.current.taskId,
      has_winner: Boolean(winnerId),
    })
  }, [finalResults, pushToast, winnerId])

  const handleShareRun = useCallback(async () => {
    try {
      const shareUrl = window.location.href
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(shareUrl)
      } else {
        const el = document.createElement('textarea')
        el.value = shareUrl
        document.body.appendChild(el)
        el.select()
        document.execCommand('copy')
        document.body.removeChild(el)
      }
      pushToast('success', 'Run URL copied')
      trackEvent('run_shared', {
        run_id: runId,
      })
    } catch {
      pushToast('error', 'Failed to copy run URL')
    }
  }, [pushToast, runId])

  const loadRunFromHistory = useCallback(
    async (historyRunId: string) => {
      setHistoryHydrationPending(true)
      navigateToView('results')
      try {
        const rawRecord = await fetchRunDetails(historyRunId)
        const record = parseRunDetailsResponse(rawRecord)
        const results = (record.results ?? {}) as RunResults
        const hydratedWinner = (record.winner_id as string | null) ?? null
        hydrateFromResults(results, hydratedWinner, { cached: false })
        const taskId = record.task_id ?? ''
        const modelId = record.model_id ?? ''
        lastRunRef.current = { taskId, modelId }
        setHasEverRun(true)
        setSelectedTaskId(taskId || selectedTaskId)
        setSelectedModelId(modelId || selectedModelId)
        const params = new URLSearchParams(window.location.search)
        params.set('run_id', historyRunId)
        window.history.replaceState(
          {},
          '',
          `${window.location.pathname}?${params.toString()}`,
        )
        pushToast('info', `Loaded run ${historyRunId}`)
      } catch (err) {
        pushToast('error', `Failed to load run: ${getErrorMessage(err)}`)
      } finally {
        setHistoryHydrationPending(false)
      }
    },
    [
      hydrateFromResults,
      navigateToView,
      pushToast,
      selectedModelId,
      selectedTaskId,
    ],
  )

  useEffect(() => {
    if (!meta) return
    void refreshRunHistory()
    void refreshLeaderboardStats()
  }, [meta, refreshLeaderboardStats, refreshRunHistory])

  useEffect(() => {
    if (activeView !== 'results' || !finalResults) {
      setDeferredResultsReady(false)
      return
    }
    let cancelled = false
    const win = window as Window & {
      requestIdleCallback?: (
        cb: () => void,
        opts?: { timeout: number },
      ) => number
      cancelIdleCallback?: (id: number) => void
    }
    if (typeof win.requestIdleCallback === 'function') {
      const idleId = win.requestIdleCallback(
        () => {
          if (!cancelled) setDeferredResultsReady(true)
        },
        { timeout: 300 },
      )
      return () => {
        cancelled = true
        if (typeof win.cancelIdleCallback === 'function') {
          win.cancelIdleCallback(idleId)
        }
      }
    }
    const timer = window.setTimeout(() => {
      if (!cancelled) setDeferredResultsReady(true)
    }, 120)
    return () => {
      cancelled = true
      window.clearTimeout(timer)
    }
  }, [activeView, finalResults])

  useEffect(() => {
    if (!meta) return
    const params = new URLSearchParams(window.location.search)
    let runIdToRestore = params.get('run_id')

    if (!runIdToRestore) {
      try {
        const raw = localStorage.getItem(CONTEXT_STORAGE_KEY)
        if (raw) {
          const parsed = JSON.parse(raw) as { run_id?: string }
          runIdToRestore = parsed.run_id ?? null
        }
      } catch {
        // storage unavailable
      }
    }

    if (runIdToRestore) {
      params.set('run_id', runIdToRestore)
      window.history.replaceState(
        {},
        '',
        `${window.location.pathname}?${params.toString()}`,
      )
      void loadRunFromHistory(runIdToRestore)
    }
  }, [loadRunFromHistory, meta])

  useEffect(() => {
    try {
      localStorage.setItem(
        CONTEXT_STORAGE_KEY,
        JSON.stringify({
          view: activeView,
          run_id: runId,
          task_id: selectedTaskId,
          model_id: selectedModelId,
        }),
      )
    } catch {
      // storage unavailable
    }
  }, [activeView, runId, selectedModelId, selectedTaskId])

  const journey = useJourneyProgress({
    isRunning,
    hasEverRun,
    finalResults,
    comparisonCount: comparisonCases.length,
    autopsyOpen: autopsyTarget !== null,
    hasExported,
  })
  const hasTask = Boolean(selectedTaskId)
  const hasModel = Boolean(selectedModelId)
  const hasRun = hasEverRun || isRunning || onboardingProgress.runStarted
  const hasResults = Boolean(finalResults) || onboardingProgress.reviewCompleted
  const hasComparison =
    comparisonCases.length > 0 || onboardingProgress.comparisonCompleted
  const activeErrorMessage = runError ?? operationError ?? null
  const resultsUiState = useMemo(
    () =>
      describeResultsWorkspaceState({
        isRunning,
        hasResults: Boolean(finalResults),
        hasError: Boolean(activeErrorMessage),
        hasBlocker:
          !isOnline ||
          connectionState === 'retrying' ||
          connectionState === 'failed',
      }),
    [activeErrorMessage, connectionState, finalResults, isOnline, isRunning],
  )
  const nextActionKey: NextActionKey = useMemo(() => {
    return resolveNextActionKey({
      hasTask,
      hasModel,
      hasRun,
      hasResults: Boolean(finalResults),
      hasComparison,
    })
  }, [finalResults, hasComparison, hasModel, hasRun, hasTask])

  const nextActionCopy = useMemo(() => buildNextActionCopy(userProfile), [userProfile])
  const railOrderVariant = useMemo<'compare_first' | 'export_first'>(
    () => (userProfile === 'executive' ? 'export_first' : postRunRailVariant),
    [postRunRailVariant, userProfile],
  )
  const roleResultsSummary = useMemo<RoleResultsSummary | null>(
    () =>
      buildRoleResultsSummary({
        results: finalResults,
        winnerId,
        scaffoldNames,
        userProfile,
      }),
    [finalResults, scaffoldNames, userProfile, winnerId],
  )
  const firstAutopsyTargetId = useMemo(() => {
    if (!finalResults) return null
    const resultIds = Object.keys(finalResults)
    if (resultIds.length === 0) return null
    return (
      resultIds.find((scaffoldId) => scaffoldId !== winnerId) ??
      resultIds[0] ??
      null
    )
  }, [finalResults, winnerId])
  const shouldShowAutopsyGuide = useMemo(
    () =>
      activeView === 'results' &&
      Boolean(finalResults) &&
      !autopsyGuideDismissed &&
      !autopsyResult &&
      Boolean(firstAutopsyTargetId),
    [
      activeView,
      autopsyGuideDismissed,
      autopsyResult,
      finalResults,
      firstAutopsyTargetId,
    ],
  )


  const runNextAction = useCallback(() => {
    executeNextActionCommand(nextActionKey, {
      navigateToView,
      runFromCurrentSelection,
      runComparison: () => {
        if (!winnerId) return
        void handleRunComparison(winnerId)
      },
      exportReport: () => {
        void handleExportReport()
      },
    })
  }, [
    handleExportReport,
    handleRunComparison,
    navigateToView,
    nextActionKey,
    runFromCurrentSelection,
    winnerId,
  ])
  const currentBlocker = useMemo(
    () =>
      resolveHelpBlocker({
        isOnline,
        connectionState,
        errorMessage: activeErrorMessage,
      }),
    [activeErrorMessage, connectionState, isOnline],
  )
  const currentPlaybook = useMemo(
    () => getTaskPlaybook(selectedTaskId || 'custom', currentBlocker),
    [currentBlocker, selectedTaskId],
  )
  const enterSafeFallbackMode = useCallback(() => {
    setSafeFallbackMode(true)
    navigateToView('history')
    pushToast(
      'info',
      'Safe fallback mode enabled. Continue with history/review workflows while live execution is blocked.',
    )
    trackEvent('fallback_mode_enabled', {
      blocker: currentPlaybook.blocker,
      task_id: selectedTaskId || 'custom',
    })
  }, [currentPlaybook.blocker, navigateToView, pushToast, selectedTaskId])
  const exitSafeFallbackMode = useCallback(() => {
    setSafeFallbackMode(false)
    pushToast('success', 'Safe fallback mode disabled. Live execution restored.')
    trackEvent('fallback_mode_disabled', {
      task_id: selectedTaskId || 'custom',
    })
  }, [pushToast, selectedTaskId])
  const resultsStateAction = useMemo(() => {
    switch (resultsUiState.kind) {
      case 'blocked':
        return {
          label: safeFallbackMode
            ? 'Open history workspace'
            : 'Enable safe fallback mode',
          run: safeFallbackMode
            ? () => navigateToView('history')
            : () => enterSafeFallbackMode(),
        }
      case 'error':
        return {
          label: 'Retry run from arena',
          run: () => navigateToView('arena'),
        }
      case 'empty':
        return {
          label: 'Open arena setup',
          run: () => navigateToView('arena'),
        }
      default:
        return null
    }
  }, [enterSafeFallbackMode, navigateToView, resultsUiState.kind, safeFallbackMode])

  const executePlaybookAction = useCallback(
    (action: PlaybookAction) => {
      trackEvent('onboarding_primary_action', {
        action,
        blocker: currentPlaybook.blocker,
        task_id: selectedTaskId || 'custom',
      })
      switch (action) {
        case 'open_settings':
          navigateToView('settings')
          return
        case 'retry':
          if (connectionState === 'failed' || connectionState === 'retrying') {
            retryConnection()
            return
          }
          runFromCurrentSelection()
          return
        case 'wait':
          pushToast('info', 'Waiting for recovery before next action.')
          return
        case 'open_tour':
          setTourStep(0)
          setTourOpen(true)
          return
        case 'open_shortcuts':
          setShortcutsOpen(true)
          return
        case 'run':
          runFromCurrentSelection()
      }
    },
    [
      connectionState,
      currentPlaybook.blocker,
      navigateToView,
      pushToast,
      retryConnection,
      runFromCurrentSelection,
      selectedTaskId,
    ],
  )

  useEffect(() => {
    if (helpOpen) {
      trackEvent('onboarding_help_opened', {
        source: helpSource,
        blocker: currentPlaybook.blocker,
        task_id: selectedTaskId || 'custom',
      })
    }
  }, [currentPlaybook.blocker, helpOpen, helpSource, selectedTaskId])

  useEffect(() => {
    const tracked = onboardingStepsTrackedRef.current
    if (hasTask && !tracked.task) {
      tracked.task = true
      trackEvent('onboarding_step_completed', { step: 'task_selected' })
    }
    if (hasModel && !tracked.model) {
      tracked.model = true
      trackEvent('onboarding_step_completed', { step: 'model_selected' })
    }
    if (hasRun && !tracked.run) {
      tracked.run = true
      trackEvent('onboarding_step_completed', { step: 'run_started' })
    }
    if (hasResults && !tracked.review) {
      tracked.review = true
      trackEvent('onboarding_step_completed', { step: 'results_reviewed' })
    }
    if (hasComparison && !tracked.comparison) {
      tracked.comparison = true
      trackEvent('onboarding_step_completed', { step: 'comparison_completed' })
    }

    setOnboardingProgress((prev) => {
      const next: OnboardingProgressState = {
        runStarted: prev.runStarted || hasRun,
        reviewCompleted: prev.reviewCompleted || hasResults,
        comparisonCompleted: prev.comparisonCompleted || hasComparison,
        milestoneShown: prev.milestoneShown,
      }
      if (
        !prev.milestoneShown &&
        next.runStarted &&
        next.reviewCompleted &&
        next.comparisonCompleted
      ) {
        next.milestoneShown = true
        pushToast('success', 'Milestone reached: full first workflow completed.')
        if (!activationTrackedRef.current) {
          activationTrackedRef.current = true
          trackEvent('activation_completed', {
            profile: userProfile,
            experience_mode: experienceMode,
          })
        }
      }
      if (
        next.runStarted === prev.runStarted &&
        next.reviewCompleted === prev.reviewCompleted &&
        next.comparisonCompleted === prev.comparisonCompleted &&
        next.milestoneShown === prev.milestoneShown
      ) {
        return prev
      }
      return next
    })
  }, [
    experienceMode,
    hasComparison,
    hasModel,
    hasResults,
    hasRun,
    hasTask,
    pushToast,
    userProfile,
  ])

  useEffect(() => {
    if (currentPlaybook.blocker === 'none') {
      if (activeBlockerRef.current) {
        trackEvent('onboarding_blocker_resolved', {
          blocker: activeBlockerRef.current.blocker,
          duration_ms: Date.now() - activeBlockerRef.current.startedAt,
          recovery_mode: safeFallbackMode ? 'safe_fallback' : 'standard',
          task_id: selectedTaskId || 'custom',
        })
        setShowFrictionFeedback(true)
      }
      blockerTrackedRef.current = null
      activeBlockerRef.current = null
      return
    }
    const key = `${currentPlaybook.blocker}:${selectedTaskId || 'custom'}`
    if (blockerTrackedRef.current === key) return
    blockerTrackedRef.current = key
    activeBlockerRef.current = {
      blocker: currentPlaybook.blocker,
      startedAt: Date.now(),
    }
    trackEvent('onboarding_blocker_detected', {
      blocker: currentPlaybook.blocker,
      task_id: selectedTaskId || 'custom',
    })
  }, [currentPlaybook.blocker, safeFallbackMode, selectedTaskId])

  const submitFrictionFeedback = useCallback(
    (sentiment: 'helpful' | 'not_helpful') => {
      trackEvent('ux_feedback_submitted', {
        sentiment,
        profile: userProfile,
        stage: journey.stage,
      })
      setShowFrictionFeedback(false)
      pushToast('success', 'Feedback captured. Thank you.')
    },
    [journey.stage, pushToast, userProfile],
  )

  useEffect(() => {
    if (!finalResults) return

    if (runId && lastTrackedRunCompleteRef.current !== runId) {
      lastTrackedRunCompleteRef.current = runId
      trackEvent('run_completed', {
        run_id: runId,
        winner_id: winnerId,
      })
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

    if (document.hidden) {
      const winnerLabel = winnerId ? scaffoldNames[winnerId] ?? winnerId : 'No winner'
      const winnerScore = winnerId
        ? finalResults[winnerId]?.evaluation?.total_score?.toFixed(1) ?? 'N/A'
        : 'N/A'
      if ('Notification' in window && Notification.permission === 'granted') {
        new Notification('Scaffold Arena run complete', {
          body: `${winnerLabel} won with score ${winnerScore}`,
        })
      }
      const originalTitle = document.title
      if (prefersReducedMotion) {
        document.title = 'Run complete'
        window.setTimeout(() => {
          document.title = originalTitle
        }, 2000)
      } else {
        let tick = 0
        const timer = window.setInterval(() => {
          document.title = tick % 2 === 0 ? 'Run complete' : originalTitle
          tick += 1
          if (tick > 6 || !document.hidden) {
            window.clearInterval(timer)
            document.title = originalTitle
          }
        }, 700)
      }
    }
  }, [
    buildCacheKey,
    finalResults,
    meta,
    prefersReducedMotion,
    refreshLeaderboardStats,
    refreshRunHistory,
    runId,
    scaffoldNames,
    winnerId,
    runMode,
  ])

  const saveCustomTask = useCallback(() => {
    if (!customTaskName.trim() || !customTaskPrompt.trim()) {
      pushToast('error', 'Custom task name and prompt are required')
      return
    }
    const id = `custom:${Date.now()}`
    const next: CustomTaskDef = {
      id,
      name: customTaskName.trim(),
      prompt: customTaskPrompt.trim(),
      schemaText: customTaskSchemaText.trim(),
    }
    setCustomTasks((prev) => [next, ...prev])
    setSelectedTaskId(id)
    setCustomTaskName('')
    setCustomTaskPrompt('')
    setCustomTaskSchemaText('')
    pushToast('success', 'Custom task saved')
  }, [
    customTaskName,
    customTaskPrompt,
    customTaskSchemaText,
    pushToast,
  ])

  const closeTour = useCallback(() => {
    setTourOpen(false)
    setTourStep(0)
    try {
      localStorage.setItem(TOUR_STORAGE_KEY, '1')
    } catch {
      // localStorage unavailable
    }
  }, [])

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
    return <LoadingSkeletons />
  }

  const showTaskSelector = activeView === 'arena' && arenaLane === 'configure'
  const personaGuidance = PERSONA_GUIDANCE[userProfile]

  // --- Main render ---
  return (
    <div className="min-h-screen bg-bg-primary flex flex-col">
      <a href="#main-content" className="skip-link">
        Skip to main content
      </a>
      <AppShellHeader
        activeView={activeView}
        stageLabel={journey.stage}
        theme={theme}
        onOpenHelp={() => openHelpCenter('header')}
        onExplainScreen={() => openHelpCenter('route')}
        onOpenTour={() => setTourOpen(true)}
        onToggleTheme={() =>
          setTheme((prev) => (prev === 'dark' ? 'light' : 'dark'))
        }
        onNavigate={navigateToView}
      />

      {showTaskSelector && (
        <div id="tour-task-selector">
          <TaskSelector
            tasks={taskOptions}
            models={models}
            isRunning={isRunning}
            selectedTaskId={selectedTaskId}
            selectedModelId={selectedModelId}
            estimatedCostUsd={estimatedCostUsd}
            onSelectTask={setSelectedTaskId}
            onSelectModel={setSelectedModelId}
            onRun={handleRun}
            onCancel={cancel}
            showMobileActionBar={false}
            showRunControls={false}
          />
        </div>
      )}

      {(runError || operationError) && (
        <div className="mx-6 mt-4 rounded border border-accent-loser/40 bg-accent-loser/10 px-4 py-3 font-mono text-xs text-accent-loser">
          {runError ?? operationError}
        </div>
      )}

      {!isOnline && (
        <div className="mx-6 mt-4 rounded border border-accent-warning/40 bg-accent-warning/10 px-4 py-3 font-mono text-xs text-accent-warning">
          {COPY.errors.offlineRunBlocked}
        </div>
      )}

      {connectionState === 'retrying' && (
        <div className="mx-6 mt-4 rounded border border-accent-warning/40 bg-accent-warning/10 px-4 py-3 font-mono text-xs text-accent-warning">
          Connection lost - retrying... (attempt {connectionRetryCount} of 5)
        </div>
      )}

      {connectionState === 'failed' && (
        <div className="mx-6 mt-4 flex items-center justify-between gap-3 rounded border border-accent-loser/40 bg-accent-loser/10 px-4 py-3 font-mono text-xs text-accent-loser">
          <span>{COPY.errors.connectionFailed}</span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={retryConnection}
              className="rounded border border-accent-loser/60 px-2 py-1 text-[11px] hover:bg-accent-loser/20"
            >
              {COPY.actions.retry}
            </button>
            <button
              type="button"
              onClick={() => openHelpCenter('banner')}
              className="rounded border border-accent-warning/60 px-2 py-1 text-[11px] text-accent-warning hover:bg-accent-warning/20"
            >
              Open help
            </button>
          </div>
        </div>
      )}
      {safeFallbackMode && (
        <div className="mx-6 mt-4 flex flex-wrap items-center justify-between gap-3 rounded border border-accent-info/40 bg-accent-info/10 px-4 py-3 font-mono text-xs text-accent-info">
          <span>
            Safe fallback mode is active. Live runs are paused while you continue with
            history, results, and reporting workflows.
          </span>
          <button
            type="button"
            onClick={exitSafeFallbackMode}
            className="rounded border border-accent-info/70 px-2 py-1 text-[11px] hover:bg-accent-info/20"
          >
            Exit fallback mode
          </button>
        </div>
      )}

      <main
        id="main-content"
        role="main"
        tabIndex={-1}
        className="flex-1 space-y-6 p-6 pb-24 sm:pb-6"
      >
        {(activeView === 'arena' || activeView === 'results') && (
          <section className="space-y-3">
            <ExperienceModeCard
              mode={experienceMode}
              profile={userProfile}
              onModeChange={setExperienceMode}
              onProfileChange={setUserProfile}
            />
            {activeView === 'results' && (
              <WorkspaceSection template="review-dense" priority="optional" className="stack-tight">
                <div className="ui-heading-sm text-text-secondary">
                  Active audience
                </div>
                <p className="text-xs text-text-secondary">
                  Persona and experience mode are global. Changes here immediately update summaries and next-action guidance.
                </p>
              </WorkspaceSection>
            )}
            {activeView !== 'arena' && <ProgressStepper steps={journey.steps} />}
          </section>
        )}

        {activeView === 'arena' && (
          <ArenaWorkspace
            arenaLane={arenaLane}
            onArenaLaneChange={setArenaLane}
            experienceMode={experienceMode}
            personaGuidance={personaGuidance}
            journeyStage={journey.stage}
            journeySteps={journey.steps}
            journeyHelpTitle={journey.helpTitle}
            journeyHelpBody={journey.helpBody}
            journeySuccessCriteria={journey.successCriteria}
            isRunning={isRunning}
            isOnline={isOnline}
            hasRun={hasRun}
            hasTask={hasTask}
            hasModel={hasModel}
            hasResults={hasResults}
            hasComparison={hasComparison}
            userProfile={userProfile}
            checklistHidden={checklistHidden}
            onChecklistHide={() => setChecklistHidden(true)}
            onChecklistShow={() => setChecklistHidden(false)}
            onTourOpen={() => setTourOpen(true)}
            selectedTaskId={selectedTaskId}
            selectedModelId={selectedModelId}
            panels={panels}
            finalResults={finalResults}
            winnerId={winnerId}
            railOrderVariant={railOrderVariant}
            currentPlaybook={currentPlaybook}
            safeFallbackMode={safeFallbackMode}
            showFrictionFeedback={showFrictionFeedback}
            runFromCurrentSelection={runFromCurrentSelection}
            onNavigateToView={navigateToView}
            onRunComparison={handleRunComparison}
            onExportReport={handleExportReport}
            onShareRun={handleShareRun}
            onExecutePlaybookAction={executePlaybookAction}
            onOpenHelpCenter={openHelpCenter}
            enterSafeFallbackMode={enterSafeFallbackMode}
            submitFrictionFeedback={submitFrictionFeedback}
            onDismissFrictionFeedback={() => setShowFrictionFeedback(false)}
          />
        )}

        {activeView === 'results' && (
          <ResultsWorkspace
            compactMode={compactMode}
            onToggleCompactMode={() => setCompactMode((prev) => !prev)}
            resultsLane={resultsLane}
            onResultsLaneChange={setResultsLane}
            resultsUiState={resultsUiState}
            resultsStateAction={resultsStateAction}
            historyHydrationPending={historyHydrationPending}
            finalResults={finalResults}
            winnerId={winnerId}
            isCachedResult={isCachedResult}
            scaffoldNames={scaffoldNames}
            userProfile={userProfile}
            roleResultsSummary={roleResultsSummary}
            shouldShowAutopsyGuide={shouldShowAutopsyGuide}
            firstAutopsyTargetId={firstAutopsyTargetId}
            comparisonCases={comparisonCases}
            comparisonLoading={comparisonLoading}
            deferredResultsReady={deferredResultsReady}
            onRunComparison={handleRunComparison}
            onRunAutopsy={handleRunAutopsy}
            onExportReport={handleExportReport}
            onExportJson={handleExportJson}
            onShare={handleShareRun}
            onNavigateToArena={() => navigateToView('arena')}
            onNavigateToHistory={() => navigateToView('history')}
            onOpenHelpCenter={openHelpCenter}
            onSetAutopsyGuideDismissed={setAutopsyGuideDismissed}
          />
        )}

        {activeView === 'history' && (
          <HistoryWorkspace
            runs={runHistory}
            onLoadRun={(runId) => {
              void loadRunFromHistory(runId)
            }}
            onStartFirstRun={runFromCurrentSelection}
          />
        )}

        {activeView === 'leaderboard' && (
          <LeaderboardWorkspace
            stats={leaderboardStats}
            scaffoldNames={scaffoldNames}
            onStartRun={runFromCurrentSelection}
          />
        )}

        {activeView === 'settings' && (
          <SettingsWorkspace
            userProfileLabel={PROFILE_AUDIENCE_LABEL[userProfile]}
            experienceMode={experienceMode}
            theme={theme}
            llmApiKey={llmApiKey}
            showLlmKey={showLlmKey}
            onLlmApiKeyChange={(key) => {
              setLlmApiKeyState(key)
              setLlmApiKey(key)
            }}
            onToggleShowLlmKey={() => setShowLlmKey((v) => !v)}
            onClearLlmKey={() => {
              const confirmed = window.confirm(
                'Clear the stored API key from this browser?',
              )
              if (!confirmed) return
              setLlmApiKeyState('')
              setLlmApiKey('')
            }}
            runMode={runMode}
            onRunModeChange={setRunMode}
            forceRerun={forceRerun}
            onForceRerunChange={setForceRerun}
            runOptions={runOptions}
            onRunOptionsChange={setRunOptions}
            enableModelMode={enableModelMode}
            modelModeScaffoldId={modelModeScaffoldId}
            onModelModeScaffoldChange={setModelModeScaffoldId}
            secondaryModelId={secondaryModelId}
            onSecondaryModelChange={setSecondaryModelId}
            models={models}
            scaffolds={scaffolds}
            modeScaffoldLabel={COPY.labels.modeScaffold}
            modeModelLabel={COPY.labels.modeModel}
            notificationPermission={notificationPermission}
            onRequestNotificationPermission={requestNotificationPermission}
            hasApiToken={hasConfiguredApiToken()}
            telemetryConsent={telemetryConsent}
            onTelemetryConsentChange={setTelemetryConsentState}
            telemetryEvents={telemetryEvents}
            customTaskName={customTaskName}
            onCustomTaskNameChange={setCustomTaskName}
            customTaskPrompt={customTaskPrompt}
            onCustomTaskPromptChange={setCustomTaskPrompt}
            customTaskSchemaText={customTaskSchemaText}
            onCustomTaskSchemaTextChange={setCustomTaskSchemaText}
            onSaveCustomTask={saveCustomTask}
            onNavigateToArena={() => navigateToView('arena')}
            activeErrorMessage={activeErrorMessage}
          />
        )}
      </main>

      {activeView !== 'arena' && (
        <MobileNextActionBar
          ctaLabel={nextActionCopy[nextActionKey].cta}
          disabled={nextActionKey === 'run_comparison' && !winnerId}
          onClick={runNextAction}
        />
      )}

      <AppFooter version={__APP_VERSION__} />

      <LiveRegion
        message={liveAnnouncement?.message ?? null}
        priority={liveAnnouncement?.priority ?? 'polite'}
      />

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

      <GuidedTourModal
        isOpen={tourOpen}
        step={tourStep}
        steps={TOUR_STEPS}
        onClose={closeTour}
        onNext={() => {
          if (tourStep >= TOUR_STEPS.length - 1) {
            closeTour()
          } else {
            setTourStep((prev) => prev + 1)
          }
        }}
      />

      <ShortcutOverlay
        isOpen={shortcutsOpen}
        onClose={() => setShortcutsOpen(false)}
      />
      <HelpCenterModal
        isOpen={helpOpen}
        isOnline={isOnline}
        connectionState={connectionState}
        hasApiToken={hasConfiguredApiToken()}
        profile={userProfile}
        taskId={selectedTaskId || 'custom'}
        errorMessage={activeErrorMessage}
        onClose={() => setHelpOpen(false)}
        onOpenTour={() => {
          setTourStep(0)
          setTourOpen(true)
        }}
        onOpenShortcuts={() => setShortcutsOpen(true)}
        onOpenSettings={() => navigateToView('settings')}
        onRetry={() => executePlaybookAction('retry')}
        onRun={runFromCurrentSelection}
      />
      <ToastStack toasts={toasts} onDismiss={dismissToast} />
    </div>
  )
}
