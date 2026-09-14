import { useCallback, useEffect, useRef, type Dispatch, type SetStateAction } from 'react'

import type { ExperienceMode, UserProfile } from '../../components/journey/ExperienceModeCard'
import type { OnboardingProgressState } from '../app/persistence'
import { trackEvent } from '../../telemetry/tracker'

interface UseOnboardingTelemetryOptions {
  helpOpen: boolean
  helpSource: string
  blocker: string
  taskId: string
  hasTask: boolean
  hasModel: boolean
  hasRun: boolean
  hasResults: boolean
  hasComparison: boolean
  safeFallbackMode: boolean
  experienceMode: ExperienceMode
  userProfile: UserProfile
  journeyStage: string
  setOnboardingProgress: Dispatch<SetStateAction<OnboardingProgressState>>
  setShowFrictionFeedback: Dispatch<SetStateAction<boolean>>
  pushToast: (type: 'error' | 'success' | 'info', message: string) => void
}

export function useOnboardingTelemetry({
  helpOpen,
  helpSource,
  blocker,
  taskId,
  hasTask,
  hasModel,
  hasRun,
  hasResults,
  hasComparison,
  safeFallbackMode,
  experienceMode,
  userProfile,
  journeyStage,
  setOnboardingProgress,
  setShowFrictionFeedback,
  pushToast,
}: UseOnboardingTelemetryOptions) {
  const stepsTrackedRef = useRef({ task: false, model: false, run: false, review: false, comparison: false })
  const activationTrackedRef = useRef(false)
  const blockerTrackedRef = useRef<string | null>(null)
  const activeBlockerRef = useRef<{ blocker: string; startedAt: number } | null>(null)

  useEffect(() => {
    if (helpOpen) {
      trackEvent('onboarding_help_opened', { source: helpSource, blocker, task_id: taskId || 'custom' })
    }
  }, [blocker, helpOpen, helpSource, taskId])

  useEffect(() => {
    const tracked = stepsTrackedRef.current
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
    setOnboardingProgress((previous) => {
      const next: OnboardingProgressState = {
        runStarted: previous.runStarted || hasRun,
        reviewCompleted: previous.reviewCompleted || hasResults,
        comparisonCompleted: previous.comparisonCompleted || hasComparison,
        milestoneShown: previous.milestoneShown,
      }
      if (!previous.milestoneShown && next.runStarted && next.reviewCompleted && next.comparisonCompleted) {
        next.milestoneShown = true
        pushToast('success', 'Milestone reached: full first workflow completed.')
        if (!activationTrackedRef.current) {
          activationTrackedRef.current = true
          trackEvent('activation_completed', { profile: userProfile, experience_mode: experienceMode })
        }
      }
      return next.runStarted === previous.runStarted &&
        next.reviewCompleted === previous.reviewCompleted &&
        next.comparisonCompleted === previous.comparisonCompleted &&
        next.milestoneShown === previous.milestoneShown
        ? previous
        : next
    })
  }, [experienceMode, hasComparison, hasModel, hasResults, hasRun, hasTask, pushToast, setOnboardingProgress, userProfile])

  useEffect(() => {
    if (blocker === 'none') {
      if (activeBlockerRef.current) {
        trackEvent('onboarding_blocker_resolved', {
          blocker: activeBlockerRef.current.blocker,
          duration_ms: Date.now() - activeBlockerRef.current.startedAt,
          recovery_mode: safeFallbackMode ? 'safe_fallback' : 'standard',
          task_id: taskId || 'custom',
        })
        setShowFrictionFeedback(true)
      }
      blockerTrackedRef.current = null
      activeBlockerRef.current = null
      return
    }
    const key = `${blocker}:${taskId || 'custom'}`
    if (blockerTrackedRef.current === key) return
    blockerTrackedRef.current = key
    activeBlockerRef.current = { blocker, startedAt: Date.now() }
    trackEvent('onboarding_blocker_detected', { blocker, task_id: taskId || 'custom' })
  }, [blocker, safeFallbackMode, setShowFrictionFeedback, taskId])

  return useCallback((sentiment: 'helpful' | 'not_helpful') => {
    trackEvent('ux_feedback_submitted', { sentiment, profile: userProfile, stage: journeyStage })
    setShowFrictionFeedback(false)
    pushToast('success', 'Feedback captured. Thank you.')
  }, [journeyStage, pushToast, setShowFrictionFeedback, userProfile])
}
