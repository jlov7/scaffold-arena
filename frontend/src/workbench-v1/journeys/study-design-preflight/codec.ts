import type { JourneySelection, PackSelection } from './types'

const EMPTY: JourneySelection = { pack: null, experimentId: null }

export function decodeJourneySelection(search: string): JourneySelection {
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search)
  const studyPackId = params.get('study_pack_id')
  const version = params.get('version')
  const experimentId = params.get('experiment_id')
  return {
    pack: studyPackId && version ? { studyPackId, version } : null,
    experimentId: experimentId || null,
  }
}

export function encodeJourneySelection(selection: JourneySelection): string {
  const params = new URLSearchParams()
  if (selection.pack) {
    params.set('study_pack_id', selection.pack.studyPackId)
    params.set('version', selection.pack.version)
  }
  if (selection.experimentId) params.set('experiment_id', selection.experimentId)
  const value = params.toString()
  return value ? `?${value}` : ''
}

export function samePack(left: PackSelection | null, right: PackSelection | null): boolean {
  return left?.studyPackId === right?.studyPackId && left?.version === right?.version
}

export { EMPTY }
