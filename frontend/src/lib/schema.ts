export interface ParsedRunRecord {
  run_id: string
  kind: string
  task_id: string
  model_id: string
  status: string
  created_at?: number
  completed_at?: number
  winner_id?: string | null
  results?: Record<string, unknown>
}

function assertObject(value: unknown, errorMessage: string): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error(errorMessage)
  }
  return value as Record<string, unknown>
}

function requiredString(obj: Record<string, unknown>, key: string): string {
  const value = obj[key]
  if (typeof value !== 'string' || value.length === 0) {
    throw new Error(`Invalid run payload: missing ${key}`)
  }
  return value
}

function optionalNumber(
  obj: Record<string, unknown>,
  key: string,
): number | undefined {
  const value = obj[key]
  if (value === undefined || value === null) return undefined
  if (typeof value !== 'number') return undefined
  return value
}

function parseRunRecord(input: unknown): ParsedRunRecord {
  const obj = assertObject(input, 'Invalid run payload')
  const winnerRaw = obj.winner_id
  return {
    run_id: requiredString(obj, 'run_id'),
    kind: requiredString(obj, 'kind'),
    task_id: requiredString(obj, 'task_id'),
    model_id: requiredString(obj, 'model_id'),
    status: requiredString(obj, 'status'),
    created_at: optionalNumber(obj, 'created_at'),
    completed_at: optionalNumber(obj, 'completed_at'),
    winner_id:
      typeof winnerRaw === 'string' || winnerRaw === null
        ? winnerRaw
        : undefined,
    results:
      obj.results && typeof obj.results === 'object' && !Array.isArray(obj.results)
        ? (obj.results as Record<string, unknown>)
        : undefined,
  }
}

export function parseRunListResponse(
  input: unknown,
): { runs: ParsedRunRecord[] } {
  const obj = assertObject(input, 'Invalid run list payload')
  if (!Array.isArray(obj.runs)) {
    throw new Error('Invalid run list payload: runs must be an array')
  }
  return { runs: obj.runs.map(parseRunRecord) }
}

export function parseRunDetailsResponse(input: unknown): ParsedRunRecord {
  try {
    return parseRunRecord(input)
  } catch {
    throw new Error('Invalid run details payload')
  }
}
