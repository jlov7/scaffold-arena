export const COPY = {
  app: {
    title: 'SCAFFOLD ARENA',
    subtitle: 'Same model, different scaffolding — wildly different results',
    breadcrumbHome: 'Home',
  },
  actions: {
    runArena: 'Run arena',
    cancelRun: 'Cancel run',
    exportReport: 'Export report',
    exportJson: 'Export JSON',
    share: 'Share run',
    takeTour: 'Take the tour',
    retry: 'Retry',
  },
  labels: {
    modeScaffold: 'Scaffold Comparison',
    modeModel: 'Model Comparison',
    noRuns: 'No runs yet',
  },
  errors: {
    offlineRunBlocked:
      'Cannot start run while offline. Reconnect and retry. If this persists, use safe fallback mode.',
    connectionFailed:
      'Connection failed. Retry stream or open Help Center. If retries keep failing, use safe fallback mode.',
    copyFailed: 'Copy failed. Retry copy or export report.',
  },
  helpers: {
    chooseTask:
      'Choose a task so quality can be judged against a clear benchmark target.',
    chooseModel:
      'Choose one model so scaffold differences are measured fairly and consistently.',
    runFlow:
      'Run the arena so each scaffold is evaluated on the same input and evidence set.',
  },
  emptyStates: {
    results:
      'Run the arena first, or load a historical run from History. Then return here to review winner quality, compare outputs, and export evidence. Learn more in Help Center.',
  },
} as const
