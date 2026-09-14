import { DisclosureRow, StatusIndicator, WorkbenchButton, WorkbenchPanel } from '../../design-system'
import type { DecisionJob, WorkbenchArea } from '../../shell'

import './decision.css'

export interface DecisionHold {
  cause: string
  consequence: string
  remediation: string
}

export interface DecisionCanvasProps {
  job: DecisionJob
  hasStudy: boolean
  hasExperiment: boolean
  hasExecution: boolean
  hold?: DecisionHold
  onNavigate: (area: WorkbenchArea) => void
}

interface DecisionCopy {
  question: string
  action: string
  destination: WorkbenchArea
  cost: string
  adequacy: string
  boundary: string
  stages: string
}

function copyFor(job: DecisionJob, hasStudy: boolean, hasExperiment: boolean, hasExecution: boolean): DecisionCopy {
  if (job === 'compare') {
    if (!hasStudy) return {
      question: 'Which study should you compare?', action: 'Choose a study', destination: 'studies',
      cost: 'No provider spend starts here. A budget estimate remains unavailable until a selected design reaches preflight.',
      adequacy: 'A listed StudyPack is a starting point, not evidence that its design is adequate for a decision.',
      boundary: 'Discovery reads the durable registry. It does not manufacture a study, provenance, cost, or result.',
      stages: 'Study → Design → Preflight → Execute → Analyze',
    }
    if (!hasExperiment) return {
      question: 'What comparison should this study make?', action: 'Design the comparison', destination: 'design',
      cost: 'The estimate is still pending the selected endpoint and frozen budget. Unknown cost is never shown as zero.',
      adequacy: 'The design must retain the declared deterministic weighting and manipulation checks before it can be preflighted.',
      boundary: 'Guided selection creates the same canonical ExperimentSpec that Lab submits.',
      stages: 'Study → Design → Preflight → Execute → Analyze',
    }
    if (!hasExecution) return {
      question: 'Is this comparison adequate and affordable enough to run?', action: 'Review preflight', destination: 'preflight',
      cost: 'Preflight is the only place that can bind the declared budget ceiling. No provider request is made by this preview.',
      adequacy: 'A local PASS is protocol admissibility only; a HOLD must be resolved before execution is requested.',
      boundary: 'The same frozen ExperimentSpec and preflight report drive Guided and Lab execution.',
      stages: 'Study → Design → Preflight → Execute → Analyze',
    }
    return {
      question: 'What does the completed comparison support?', action: 'Review the decision', destination: 'analyze',
      cost: 'Observed cost remains unknown unless provider usage and the configured price evidence reconcile.',
      adequacy: 'Analysis reports only cover the included durable attempts and their stated exclusions.',
      boundary: 'A comparison result is bounded by its report, evidence ceiling, and reproduction action.',
      stages: 'Study → Design → Preflight → Execute → Analyze',
    }
  }
  if (job === 'diagnose') return {
    question: 'What should you inspect before changing a harness?', action: 'Open Harness Home / X-Ray', destination: 'xray',
    cost: 'X-Ray inspects a captured source snapshot. It starts no provider and has no provider cost.',
    adequacy: 'Static evidence can diagnose candidate mechanisms; it cannot prove runtime behavior, safety, or cause.',
    boundary: 'Use Trace / Counterfactual Lab only for persisted records and preserve unknowns.',
    stages: 'X-Ray → Observatory → Trace / Counterfactual Lab',
  }
  if (job === 'improve') return {
    question: 'What is the next bounded experiment worth planning?', action: 'Open Arena Forge', destination: 'forge',
    cost: 'Forge simulates declared designs inside a fixed budget. It does not start an experiment or provider.',
    adequacy: 'A candidate needs independent evaluation and a separate admission before it can become operational work.',
    boundary: 'Forge proposes; the durable protocol and a human or policy admit.',
    stages: 'Forge → Design → Preflight → Execute → Analyze',
  }
  return {
    question: 'What can the available evidence actually prove?', action: 'Open Evidence Room', destination: 'evidence',
    cost: 'Unknown usage and cost remain unknown in every evidence receipt and decision brief.',
    adequacy: 'Integrity and custody do not establish outcome correctness, causal effect, production readiness, or independent reproduction.',
    boundary: 'Every result needs its evidence ceiling and a reproduction or verification action before use.',
    stages: 'Analyze → Trace / Counterfactual Lab → Review → Evidence',
  }
}

export function DecisionCanvas({ job, hasStudy, hasExperiment, hasExecution, hold, onNavigate }: DecisionCanvasProps) {
  const copy = copyFor(job, hasStudy, hasExperiment, hasExecution)
  return <section className="sa-decision" aria-labelledby="decision-heading">
    {hold && <section className="sa-severe-banner" role="alert"><div><strong>Decision HOLD</strong><dl className="sa-decision-hold"><div><dt>Cause</dt><dd>{hold.cause}</dd></div><div><dt>Consequence</dt><dd>{hold.consequence}</dd></div><div><dt>Remediation</dt><dd>{hold.remediation}</dd></div></dl></div></section>}
    <WorkbenchPanel title={<span id="decision-heading">{job[0].toUpperCase() + job.slice(1)}</span>} action={<StatusIndicator tone={hold ? 'warning' : 'info'}>{hold ? 'HOLD' : 'Decision guide'}</StatusIndicator>}>
      <p className="sa-decision-question">{copy.question}</p>
      <div className="sa-decision-preview" aria-label="Cost and adequacy preview"><div><strong>Cost preview</strong><span>{copy.cost}</span></div><div><strong>Adequacy preview</strong><span>{copy.adequacy}</span></div></div>
      <p className="sa-decision-boundary">{copy.boundary}</p>
      <div className="sa-journey-actions"><WorkbenchButton tone="primary" onClick={() => onNavigate(copy.destination)}>{copy.action}</WorkbenchButton></div>
      <DisclosureRow title="Underlying protocol path"><p>{copy.stages}</p></DisclosureRow>
    </WorkbenchPanel>
  </section>
}
