import type { ExecutionProvenance, JsonObject } from '../../../api/v1/client'

const digest = /^[a-f0-9]{64}$/
const requiredIdentity = ['code_revision', 'runtime_image'] as const
const requiredDigests = ['code_hash', 'runtime_image_hash', 'environment_hash', 'prompt_hash', 'context_hash', 'tool_hash'] as const

export const EMPTY_PROVENANCE: ExecutionProvenance = {
  protocol_version: '1.0',
  code_revision: '',
  code_hash: '',
  runtime_image: '',
  runtime_image_hash: '',
  environment_hash: '',
  prompt_hash: '',
  context_hash: '',
  tool_hash: '',
  source_refs: [],
  captured_at: '',
}

function record(value: unknown): JsonObject | null {
  return value !== null && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : null
}

function stringField(value: JsonObject, key: string): string {
  return typeof value[key] === 'string' ? value[key].trim() : ''
}

function dateIsTimezoneAware(value: string): boolean {
  if (!value || !/(Z|[+-]\d\d:\d\d)$/.test(value)) return false
  return Number.isFinite(Date.parse(value))
}

export function validateProvenance(candidate: unknown): { provenance: ExecutionProvenance | null; errors: string[] } {
  const value = record(candidate)
  if (!value) return { provenance: null, errors: ['ExecutionProvenance must be a JSON object.'] }
  const errors: string[] = []
  for (const field of requiredIdentity) if (!stringField(value, field)) errors.push(`${field} is required and cannot be blank.`)
  for (const field of requiredDigests) if (!digest.test(stringField(value, field))) errors.push(`${field} must be a lowercase SHA-256 digest (64 hexadecimal characters).`)
  const sourceRefs = Array.isArray(value.source_refs) ? value.source_refs : null
  if (!sourceRefs || sourceRefs.length === 0) {
    errors.push('At least one source reference with its content hash is required.')
  } else {
    const seen = new Set<string>()
    sourceRefs.forEach((source, index) => {
      const item = record(source)
      const uri = item ? stringField(item, 'source_uri') : ''
      const contentHash = item ? stringField(item, 'content_hash') : ''
      if (!uri) errors.push(`Source ${index + 1} requires source_uri.`)
      if (!digest.test(contentHash)) errors.push(`Source ${index + 1} content_hash must be a lowercase SHA-256 digest.`)
      const identity = `${uri}\u0000${contentHash}`
      if (uri && contentHash && seen.has(identity)) errors.push(`Source ${index + 1} duplicates an existing source URI/hash pair.`)
      seen.add(identity)
    })
  }
  const capturedAt = stringField(value, 'captured_at')
  if (!dateIsTimezoneAware(capturedAt)) errors.push('captured_at must be a valid timezone-aware ISO 8601 timestamp.')
  const protocolVersion = value.protocol_version
  if (protocolVersion !== undefined && protocolVersion !== '1.0') errors.push('protocol_version must be 1.0 when supplied.')
  if (errors.length) return { provenance: null, errors }

  return {
    provenance: {
      protocol_version: protocolVersion === '1.0' ? protocolVersion : '1.0',
      code_revision: stringField(value, 'code_revision'),
      code_hash: stringField(value, 'code_hash'),
      runtime_image: stringField(value, 'runtime_image'),
      runtime_image_hash: stringField(value, 'runtime_image_hash'),
      environment_hash: stringField(value, 'environment_hash'),
      prompt_hash: stringField(value, 'prompt_hash'),
      context_hash: stringField(value, 'context_hash'),
      tool_hash: stringField(value, 'tool_hash'),
      source_refs: sourceRefs!.map((source) => {
        const item = record(source)!
        return { source_uri: stringField(item, 'source_uri'), content_hash: stringField(item, 'content_hash') }
      }),
      captured_at: capturedAt,
    },
    errors: [],
  }
}

export function parseProvenance(text: string): { provenance: ExecutionProvenance | null; errors: string[] } {
  try {
    return validateProvenance(JSON.parse(text) as unknown)
  } catch (error) {
    return { provenance: null, errors: [error instanceof Error ? `Malformed JSON: ${error.message}` : 'Malformed JSON.'] }
  }
}

export function formatCost(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `$${value.toFixed(4)}` : 'UNKNOWN'
}
