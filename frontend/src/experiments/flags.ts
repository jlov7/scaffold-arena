export type FeatureFlag = 'enable_model_mode'

const FLAG_DEFAULTS: Record<FeatureFlag, boolean> = {
  enable_model_mode: true,
}

function storageKey(flag: FeatureFlag): string {
  return `scaffold_arena_flag_${flag}`
}

export function getFeatureFlag(flag: FeatureFlag): boolean {
  try {
    const stored = localStorage.getItem(storageKey(flag))
    if (stored === '1') return true
    if (stored === '0') return false
  } catch {
    // ignore storage issues
  }
  return FLAG_DEFAULTS[flag]
}

export function setFeatureFlagOverride(flag: FeatureFlag, enabled: boolean): void {
  try {
    localStorage.setItem(storageKey(flag), enabled ? '1' : '0')
  } catch {
    // ignore storage issues
  }
}

export function clearFeatureFlagOverride(flag: FeatureFlag): void {
  try {
    localStorage.removeItem(storageKey(flag))
  } catch {
    // ignore storage issues
  }
}
