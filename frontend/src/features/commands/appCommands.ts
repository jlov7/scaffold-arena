import type { AppView } from '../../app/viewState'
import type { NextActionKey } from '../journey/nextAction'

export interface AppCommandHandlers {
  navigateToView: (view: AppView) => void
  runFromCurrentSelection: () => void
  runComparison: () => void
  exportReport: () => void
}

export function executeNextActionCommand(
  key: NextActionKey,
  handlers: AppCommandHandlers,
): void {
  switch (key) {
    case 'pick_task':
    case 'pick_model':
      handlers.navigateToView('arena')
      return
    case 'run':
      handlers.navigateToView('arena')
      handlers.runFromCurrentSelection()
      return
    case 'review_results':
      handlers.navigateToView('results')
      return
    case 'run_comparison':
      handlers.runComparison()
      return
    case 'export_report':
      handlers.exportReport()
  }
}
