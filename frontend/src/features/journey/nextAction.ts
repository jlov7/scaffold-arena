import type { UserProfile } from '../../components/journey/ExperienceModeCard'

export type NextActionKey =
  | 'pick_task'
  | 'pick_model'
  | 'run'
  | 'review_results'
  | 'run_comparison'
  | 'export_report'

export interface NextActionCopy {
  title: string
  body: string
  cta: string
}

export function resolveNextActionKey(params: {
  hasTask: boolean
  hasModel: boolean
  hasRun: boolean
  hasResults: boolean
  hasComparison: boolean
}): NextActionKey {
  const { hasTask, hasModel, hasRun, hasResults, hasComparison } = params
  if (!hasTask) return 'pick_task'
  if (!hasModel) return 'pick_model'
  if (!hasRun) return 'run'
  if (!hasResults) return 'review_results'
  if (!hasComparison) return 'run_comparison'
  return 'export_report'
}

export function buildNextActionCopy(
  userProfile: UserProfile,
): Record<NextActionKey, NextActionCopy> {
  const base: Record<NextActionKey, NextActionCopy> = {
    pick_task: {
      title: 'Choose a benchmark task',
      body: 'Pick the scenario you want to evaluate so quality has a clear target.',
      cta: 'Go to task setup',
    },
    pick_model: {
      title: 'Choose a model',
      body: 'Select one model to compare scaffolds fairly on identical input.',
      cta: 'Select model now',
    },
    run: {
      title: 'Run the arena',
      body: 'Execute all scaffolds once to unlock comparison and evidence workflows.',
      cta: 'Run arena now',
    },
    review_results: {
      title: 'Review results',
      body: 'Open the Results workspace to inspect winner quality, cost, and output diff.',
      cta: 'Open results workspace',
    },
    run_comparison: {
      title: 'Run proof comparison',
      body: 'Validate orchestration value through the canonical comparison flow.',
      cta: 'Run proof comparison',
    },
    export_report: {
      title: 'Export your evidence',
      body: 'Capture a shareable report so your decision is reproducible and review-ready.',
      cta: 'Export report',
    },
  }

  if (userProfile === 'executive') {
    base.review_results = {
      title: 'Confirm winner snapshot',
      body: 'Use the concise summary to confirm winner, score, cost, and time quickly.',
      cta: 'Open executive summary',
    }
    base.run_comparison = {
      title: 'Validate business case',
      body: 'Run proof comparison to show why the orchestration choice matters financially.',
      cta: 'Run business-case proof',
    }
    base.export_report = {
      title: 'Share decision brief',
      body: 'Export a concise report for stakeholder review and sign-off.',
      cta: 'Export decision brief',
    }
  } else if (userProfile === 'operator') {
    base.run = {
      title: 'Run reliability check',
      body: 'Execute the run and verify retries, latency, and blocker behavior.',
      cta: 'Run reliability pass',
    }
    base.run_comparison = {
      title: 'Compare operational tradeoffs',
      body: 'Use proof comparison to quantify quality vs cost vs stability tradeoffs.',
      cta: 'Run ops comparison',
    }
  } else if (userProfile === 'analyst') {
    base.review_results = {
      title: 'Inspect evidence depth',
      body: 'Review score breakdown and output diff before declaring a winner.',
      cta: 'Open evidence workspace',
    }
    base.export_report = {
      title: 'Package analytical rationale',
      body: 'Export traceable evidence and recommendations for peer review.',
      cta: 'Export analysis report',
    }
  }

  return base
}
