import type { createArenaV1, ExperimentSpec, JsonObject, StudyPack } from '../../../api/v1/client'

export type ArenaV1Client = ReturnType<typeof createArenaV1>

export interface PackSelection {
  studyPackId: string
  version: string
}

export interface JourneySelection {
  pack: PackSelection | null
  experimentId: string | null
}

export type CanonicalExperiment = ExperimentSpec & JsonObject
export type CanonicalStudyPack = StudyPack & JsonObject

export const FIXTURE_LABEL = 'Synthetic fixture — not benchmark evidence.'

export function asRecord(value: unknown): JsonObject {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as JsonObject : {}
}

export function asArray(value: unknown): JsonObject[] {
  return Array.isArray(value) ? value.map(asRecord) : []
}

export function stringValue(value: unknown, fallback = 'Unknown'): string {
  return typeof value === 'string' && value.length > 0 ? value : fallback
}

export function numberValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback
}

export function product(values: readonly number[]): number {
  return values.reduce((total, value) => total * Math.max(0, value), 1)
}

export function designExpansion(spec: JsonObject): number {
  const design = stringValue(spec.design, 'full')
  if (design === 'custom') return Array.isArray(spec.custom_design) ? spec.custom_design.length : 0
  if (design === 'fractional') return Array.isArray(spec.custom_design) && spec.custom_design.length > 0 ? spec.custom_design.length : 0
  return product(asArray(spec.factors).map((factor) => Array.isArray(factor.levels) ? factor.levels.length : 0))
}

export function expectedAttempts(spec: JsonObject): number {
  return designExpansion(spec)
    * (Array.isArray(spec.scenario_ids) ? spec.scenario_ids.length : 0)
    * (Array.isArray(spec.harness_ids) ? spec.harness_ids.length : 0)
    * Math.max(Array.isArray(spec.model_endpoints) ? spec.model_endpoints.length : 0, 1)
    * Math.max(1, numberValue(spec.repetitions, 1))
}

export function fixturePack(pack: JsonObject | null): boolean {
  if (!pack) return false
  return stringValue(pack.study_pack_id, '').includes('offline-demo')
    || asArray(pack.scenarios).some((scenario) => stringValue(scenario.source_label, '') === 'synthetic')
}

export function problemMessage(error: unknown): { kind: 'offline' | 'permission' | 'hold' | 'error'; message: string } {
  const record = asRecord(error)
  const status = numberValue(record.status)
  const code = stringValue(record.code, '')
  const message = error instanceof Error ? error.message : 'The request could not be completed.'
  if (status === 401 || status === 403 || /project|permission|authoriz/i.test(code)) return { kind: 'permission', message }
  if (status === 409 || record.verdict === 'HOLD') return { kind: 'hold', message }
  if (status === 0 || status === 502 || status === 503 || status === 504 || error instanceof TypeError) return { kind: 'offline', message }
  return { kind: 'error', message }
}

export function isRecord(value: unknown): value is JsonObject {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}
