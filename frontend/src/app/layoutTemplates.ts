export type LayoutTemplate = 'setup-heavy' | 'run-live' | 'review-dense'

export function classesForTemplate(template: LayoutTemplate): string {
  switch (template) {
    case 'setup-heavy':
      return 'layout-template-setup'
    case 'run-live':
      return 'layout-template-live'
    case 'review-dense':
      return 'layout-template-review'
  }
}

export function classesForPriority(
  priority: 'critical' | 'important' | 'optional',
): string {
  switch (priority) {
    case 'critical':
      return 'surface-critical'
    case 'important':
      return 'surface-important'
    case 'optional':
      return 'surface-optional'
  }
}
