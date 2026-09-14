import type { LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

export const DECISION_AREAS = ['compare', 'diagnose', 'improve', 'prove'] as const
export const LAB_WORKBENCH_AREAS = ['studies', 'design', 'preflight', 'execute', 'analyze', 'xray', 'observatory', 'counterfactual', 'forge', 'trace-lab', 'review', 'evidence', 'settings'] as const
export const WORKBENCH_AREAS = [...DECISION_AREAS, ...LAB_WORKBENCH_AREAS] as const
export type WorkbenchArea = (typeof WORKBENCH_AREAS)[number]
export type DecisionJob = (typeof DECISION_AREAS)[number]
export type WorkbenchMode = 'guided' | 'lab'

export interface WorkbenchNavigationItem {
  id: WorkbenchArea
  label: string
  icon: LucideIcon
}

export interface WorkbenchStatus {
  label: string
  value: ReactNode
  tone?: 'ready' | 'info' | 'warning' | 'failure' | 'offline'
}

export interface WorkbenchShellProps {
  activeArea: WorkbenchArea
  onNavigate: (area: WorkbenchArea) => void
  mode: WorkbenchMode
  onModeChange: (mode: WorkbenchMode) => void
  children: ReactNode
  evidence: ReactNode
  title?: string
  version?: string
  studyLabel?: ReactNode
  specTitle?: ReactNode
  specLabel?: ReactNode
  statuses?: WorkbenchStatus[]
  stageTitle?: string
}
