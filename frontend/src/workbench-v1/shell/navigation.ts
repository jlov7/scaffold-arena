import { Activity, Atom, Beaker, BookOpen, FileSearch, FlaskConical, GitCompareArrows, Hammer, ListChecks, Microscope, Orbit, ShieldCheck, SlidersHorizontal, Sparkles } from 'lucide-react'

import type { DecisionJob, WorkbenchArea, WorkbenchNavigationItem } from './types'

export const WORKBENCH_NAVIGATION: ReadonlyArray<WorkbenchNavigationItem> = [
  { id: 'compare', label: 'Compare', icon: GitCompareArrows },
  { id: 'diagnose', label: 'Diagnose', icon: FileSearch },
  { id: 'improve', label: 'Improve', icon: Sparkles },
  { id: 'prove', label: 'Prove', icon: ShieldCheck },
]

export const LAB_WORKBENCH_NAVIGATION: ReadonlyArray<WorkbenchNavigationItem> = [
  { id: 'studies', label: 'Study Canvas', icon: BookOpen },
  { id: 'design', label: 'Design', icon: Beaker },
  { id: 'preflight', label: 'Preflight', icon: ListChecks },
  { id: 'execute', label: 'Run Cockpit', icon: Activity },
  { id: 'analyze', label: 'Decision Canvas', icon: Atom },
  { id: 'xray', label: 'Harness Home / X-Ray', icon: Microscope },
  { id: 'observatory', label: 'Observatory', icon: Orbit },
  { id: 'counterfactual', label: 'Trace / Counterfactual Lab', icon: GitCompareArrows },
  { id: 'forge', label: 'Arena Forge', icon: Hammer },
  { id: 'trace-lab', label: 'Trace internals', icon: FileSearch },
  { id: 'review', label: 'Review', icon: FlaskConical },
  { id: 'evidence', label: 'Evidence Room', icon: SlidersHorizontal },
  { id: 'settings', label: 'Settings', icon: SlidersHorizontal },
]

export const MOBILE_GUIDED_AREAS: DecisionJob[] = ['compare', 'diagnose', 'improve', 'prove']
export const MOBILE_LAB_AREAS: WorkbenchArea[] = ['studies', 'design', 'execute', 'analyze']

export function primaryDecisionForArea(area: WorkbenchArea): DecisionJob {
  if (area === 'compare' || area === 'diagnose' || area === 'improve' || area === 'prove') return area
  if (area === 'xray' || area === 'observatory' || area === 'counterfactual' || area === 'trace-lab') return 'diagnose'
  if (area === 'forge') return 'improve'
  if (area === 'evidence' || area === 'review' || area === 'settings') return 'prove'
  return 'compare'
}
