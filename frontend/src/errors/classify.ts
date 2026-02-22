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

function extractStatusCode(message: string): number | null {
  const match = message.match(/\b(\d{3})\b/)
  if (!match) return null
  const status = Number(match[1])
  return Number.isFinite(status) ? status : null
}

export function classifyApiError(message: string): ClassifiedError {
  const lower = message.toLowerCase()
  const statusCode = extractStatusCode(message)

  if (statusCode === 401 || statusCode === 403 || lower.includes('unauthorized')) {
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
      return 'Check your API token and session settings.'
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
