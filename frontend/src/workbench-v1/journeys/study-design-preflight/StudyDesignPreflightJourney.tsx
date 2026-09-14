import { DesignSurface } from '../../surfaces/design'
import { PreflightSurface } from '../../surfaces/preflight'
import { StudiesSurface } from '../../surfaces/studies'
import { useStudyDesignPreflightJourney } from './controller'
import './journey.css'
import { type ArenaV1Client, type JourneySelection } from './types'

export type StudyDesignPreflightStage = 'studies' | 'design' | 'preflight'

export interface StudyDesignPreflightJourneyProps {
  client: ArenaV1Client
  stage: StudyDesignPreflightStage
  mode: 'guided' | 'lab'
  initialSearch?: string
  selection?: JourneySelection
  onSelectionChange?: (selection: JourneySelection) => void
  onNavigate?: (stage: StudyDesignPreflightStage) => void
  onProceedToExecute?: () => void
  projectId?: string
}

export function StudyDesignPreflightJourney({ client, stage, mode, initialSearch, selection: externalSelection, onSelectionChange, onNavigate, onProceedToExecute, projectId }: StudyDesignPreflightJourneyProps) {
  const journey = useStudyDesignPreflightJourney(initialSearch, externalSelection, onSelectionChange)
  if (stage === 'studies') return <StudiesSurface client={client} selection={journey.selection.pack} onSelect={journey.selectPack} projectId={projectId} />
  if (stage === 'design') return <DesignSurface client={client} packSelection={journey.selection.pack} experimentId={journey.selection.experimentId} mode={mode} onExperimentSelected={journey.selectExperiment} onNavigateToStudies={() => onNavigate?.('studies')} projectId={projectId} />
  return <PreflightSurface client={client} experimentId={journey.selection.experimentId} projectId={projectId} isFixture={journey.selection.pack?.studyPackId === 'offline-demo-v1'} onNavigateToDesign={() => onNavigate?.('design')} onProceedToExecute={onProceedToExecute} />
}
