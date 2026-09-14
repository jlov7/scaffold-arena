export interface OnboardingProgressState {
  runStarted: boolean
  reviewCompleted: boolean
  comparisonCompleted: boolean
  milestoneShown: boolean
}

export function readOnboardingProgress(storageKey: string): OnboardingProgressState {
  try {
    const raw = localStorage.getItem(storageKey)
    if (!raw) {
      return {
        runStarted: false,
        reviewCompleted: false,
        comparisonCompleted: false,
        milestoneShown: false,
      }
    }
    const parsed = JSON.parse(raw) as Partial<OnboardingProgressState>
    return {
      runStarted: Boolean(parsed.runStarted),
      reviewCompleted: Boolean(parsed.reviewCompleted),
      comparisonCompleted: Boolean(parsed.comparisonCompleted),
      milestoneShown: Boolean(parsed.milestoneShown),
    }
  } catch {
    return {
      runStarted: false,
      reviewCompleted: false,
      comparisonCompleted: false,
      milestoneShown: false,
    }
  }
}

export function readBooleanFlag(storageKey: string): boolean {
  try {
    return localStorage.getItem(storageKey) === '1'
  } catch {
    return false
  }
}

export function readCompactMode(storageKey: string): boolean {
  try {
    const stored = localStorage.getItem(storageKey)
    if (stored === '1') return true
    if (stored === '0') return false
  } catch {
    // storage unavailable
  }
  return window.matchMedia('(max-width: 1024px)').matches
}
