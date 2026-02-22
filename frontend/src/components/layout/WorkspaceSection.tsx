import type { ReactNode } from 'react'

import {
  classesForPriority,
  classesForTemplate,
  type LayoutTemplate,
} from '../../app/layoutTemplates'

interface WorkspaceSectionProps {
  template: LayoutTemplate
  priority?: 'critical' | 'important' | 'optional'
  className?: string
  children: ReactNode
}

export function WorkspaceSection({
  template,
  priority = 'important',
  className = '',
  children,
}: WorkspaceSectionProps) {
  return (
    <section
      className={[
        'rounded-lg border p-4',
        classesForTemplate(template),
        classesForPriority(priority),
        className,
      ].join(' ')}
    >
      {children}
    </section>
  )
}
