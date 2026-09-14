export type ErrorKind =
  | 'auth'
  | 'rate_limit'
  | 'validation'
  | 'server'
  | 'network'
  | 'unknown'

export interface ClassifiedError {
  kind: ErrorKind
  statusCode: number | null
}

function truncateDetail(detail: string): string {
  const trimmed = detail.trim()
  if (trimmed.length <= 180) return trimmed
  return `${trimmed.slice(0, 177)}...`
}

function extractStatusCode(message: string): number | null {
  const match = message.match(/\b(\d{3})\b/)
  if (!match) return null
  const status = Number(match[1])
  return Number.isFinite(status) ? status : null
}

export function extractApiErrorDetail(message: string): string | null {
  const jsonStart = message.indexOf('{')
  if (jsonStart >= 0) {
    try {
      const parsed = JSON.parse(message.slice(jsonStart)) as {
        detail?: unknown
        message?: unknown
        error?: unknown
      }
      if (typeof parsed.detail === 'string') return truncateDetail(parsed.detail)
      if (typeof parsed.message === 'string') return truncateDetail(parsed.message)
      if (typeof parsed.error === 'string') return truncateDetail(parsed.error)
      if (
        parsed.error &&
        typeof parsed.error === 'object' &&
        'message' in parsed.error &&
        typeof parsed.error.message === 'string'
      ) {
        return truncateDetail(parsed.error.message)
      }
    } catch {
      return null
    }
  }

  const withoutStatus = message.replace(/^\s*\d{3}\s*:?\s*/, '').trim()
  if (!withoutStatus || withoutStatus.startsWith('{')) return null
  return truncateDetail(withoutStatus)
}

export function classifyApiError(message: string): ClassifiedError {
  const lower = message.toLowerCase()
  const statusCode = extractStatusCode(message)

  if (
    statusCode === 401 ||
    statusCode === 403 ||
    lower.includes('unauthorized') ||
    lower.includes('authorization')
  ) {
    return { kind: 'auth', statusCode }
  }
  if (statusCode === 429 || lower.includes('rate')) {
    return { kind: 'rate_limit', statusCode }
  }
  if (
    statusCode === 400 ||
    statusCode === 413 ||
    statusCode === 422 ||
    lower.includes('validation')
  ) {
    return { kind: 'validation', statusCode }
  }
  if (
    (statusCode !== null && statusCode >= 500) ||
    lower.includes('server error') ||
    lower.includes('internal')
  ) {
    return { kind: 'server', statusCode }
  }
  if (lower.includes('network') || lower.includes('failed to fetch')) {
    return { kind: 'network', statusCode }
  }
  return { kind: 'unknown', statusCode }
}

export function remediationForErrorKind(kind: ErrorKind): string {
  switch (kind) {
    case 'auth':
      return 'Add the local API token in Settings, then retry.'
    case 'rate_limit':
      return 'Wait a moment, then retry the action.'
    case 'validation':
      return 'Review your inputs and try again.'
    case 'server':
      return 'Temporary server issue. Retry shortly.'
    case 'network':
      return 'Check your network connection and retry.'
    case 'unknown':
      return 'Retry the action. If it persists, inspect logs.'
  }
}

export function formatApiErrorMessage(message: string): string {
  const raw = message.trim() || 'Unexpected request failure.'
  const classified = classifyApiError(raw)
  const detail = extractApiErrorDetail(raw)
  const status = classified.statusCode ? ` (${classified.statusCode})` : ''
  const detailLower = detail?.toLowerCase() ?? raw.toLowerCase()

  if (
    classified.kind === 'auth' &&
    (detailLower.includes('x-api-key') ||
      detailLower.includes('provider') ||
      detailLower.includes('anthropic') ||
      detailLower.includes('openai') ||
      detailLower.includes('gemini') ||
      detailLower.includes('openrouter'))
  ) {
    return `Provider key rejected${status}. Update the model provider key in Settings or server config, then retry.`
  }

  switch (classified.kind) {
    case 'auth':
      return `API token required${status}. ${remediationForErrorKind(classified.kind)}`
    case 'rate_limit':
      return `Rate limit hit${status}. ${remediationForErrorKind(classified.kind)}`
    case 'validation':
      return detail
        ? `Request validation failed${status}: ${detail}. ${remediationForErrorKind(classified.kind)}`
        : `Request validation failed${status}. ${remediationForErrorKind(classified.kind)}`
    case 'server':
      return detail
        ? `Server request failed${status}: ${detail}. ${remediationForErrorKind(classified.kind)}`
        : `Server request failed${status}. ${remediationForErrorKind(classified.kind)}`
    case 'network':
      return `Network request failed${status}. ${remediationForErrorKind(classified.kind)}`
    case 'unknown':
      return detail
        ? `Request failed${status}: ${detail}. ${remediationForErrorKind(classified.kind)}`
        : `Request failed${status}. ${remediationForErrorKind(classified.kind)}`
  }
}
