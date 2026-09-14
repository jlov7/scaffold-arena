import type { TelemetryEvent, TelemetryEventName } from './events'

const TELEMETRY_CONSENT_KEY = 'scaffold_arena_telemetry_consent'

function bucket(): TelemetryEvent[] {
  const win = window as Window & { __arenaTelemetryEvents?: TelemetryEvent[] }
  if (!Array.isArray(win.__arenaTelemetryEvents)) {
    win.__arenaTelemetryEvents = []
  }
  return win.__arenaTelemetryEvents
}

export function readTrackedEvents(): TelemetryEvent[] {
  return bucket().slice()
}

export function getTelemetryConsent(): boolean {
  try {
    return localStorage.getItem(TELEMETRY_CONSENT_KEY) === '1'
  } catch {
    return false
  }
}

export function setTelemetryConsent(enabled: boolean): void {
  try {
    if (enabled) {
      localStorage.setItem(TELEMETRY_CONSENT_KEY, '1')
    } else {
      localStorage.removeItem(TELEMETRY_CONSENT_KEY)
    }
  } catch {
    // storage unavailable
  }
}

export function trackEvent(
  name: TelemetryEventName,
  payload: Record<string, unknown> = {},
): void {
  if (!getTelemetryConsent()) return
  const event: TelemetryEvent = { name, payload, ts_ms: Date.now() }
  bucket().push(event)
}

export function resetTrackerForTests(): void {
  const win = window as Window & { __arenaTelemetryEvents?: TelemetryEvent[] }
  win.__arenaTelemetryEvents = []
}
