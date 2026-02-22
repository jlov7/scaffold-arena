import { useMemo } from 'react'

import {
  resolveJourneyStage,
  type JourneySignals,
  type JourneyStage,
} from './stateMachine'

export interface JourneyStep {
  id: 'setup' | 'run' | 'review' | 'iterate'
  label: string
  status: 'complete' | 'current' | 'upcoming'
}

export type { JourneyStage }

const STEP_ORDER: JourneyStep['id'][] = ['setup', 'run', 'review', 'iterate']

export function useJourneyProgress(input: JourneySignals): {
  stage: JourneyStage
  steps: JourneyStep[]
  helpTitle: string
  helpBody: string
  successCriteria: string
} {
  return useMemo(() => {
    const stage = resolveJourneyStage(input)
    const stageIndex = STEP_ORDER.indexOf(
      stage === 'running' ? 'run' : stage,
    )

    const steps: JourneyStep[] = STEP_ORDER.map((id, index) => {
      if (index < stageIndex) {
        return { id, label: labelForStep(id), status: 'complete' }
      }
      if (index === stageIndex) {
        return { id, label: labelForStep(id), status: 'current' }
      }
      return { id, label: labelForStep(id), status: 'upcoming' }
    })

    const help = helpForStage(stage)

    return {
      stage,
      steps,
      helpTitle: help.title,
      helpBody: help.body,
      successCriteria: help.successCriteria,
    }
  }, [input])
}

function labelForStep(step: JourneyStep['id']): string {
  switch (step) {
    case 'setup':
      return 'Choose task and model'
    case 'run':
      return 'Run arena'
    case 'review':
      return 'Review scoreboard'
    case 'iterate':
      return 'Compare, autopsy, export'
  }
}

function helpForStage(
  stage: JourneyStage,
): { title: string; body: string; successCriteria: string } {
  switch (stage) {
    case 'setup':
      return {
        title: 'Start with a concrete benchmark',
        body: 'Pick one task and one model. The same input is sent through each scaffold so the quality delta is attributable to orchestration.',
        successCriteria: 'Task and model selected with clear benchmark intent.',
      }
    case 'running':
      return {
        title: 'Focus mode is on',
        body: 'The run is in progress. Wait for all panels to complete before comparing scores to avoid partial conclusions.',
        successCriteria: 'All scaffold panels complete without unresolved failures.',
      }
    case 'review':
      return {
        title: 'Use score, cost, and time together',
        body: 'Judge winners by total score and cost efficiency. A slightly lower score can still win on cost per point.',
        successCriteria: 'A winner is selected and its tradeoff is understood.',
      }
    case 'iterate':
      return {
        title: 'Turn findings into action',
        body: 'Run proof comparison, open autopsy on weaker scaffolds, then export a report so the decision is reproducible.',
        successCriteria: 'Comparison/autopsy evidence captured and report-ready.',
      }
  }
}
