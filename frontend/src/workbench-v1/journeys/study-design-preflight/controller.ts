import { useState } from 'react'
import { decodeJourneySelection } from './codec'
import type { JourneySelection, PackSelection } from './types'

export function useStudyDesignPreflightJourney(initialSearch = '', external?: JourneySelection, onChange?: (selection: JourneySelection) => void) {
  const [internal, setInternal] = useState<JourneySelection>(() => decodeJourneySelection(initialSearch))
  const selection = external ?? internal
  const update = (next: JourneySelection) => {
    if (!external) setInternal(next)
    onChange?.(next)
  }
  return {
    selection,
    selectPack: (pack: PackSelection) => update({ pack, experimentId: null }),
    selectExperiment: (experimentId: string) => update({ pack: selection.pack, experimentId }),
  }
}
