export type UiStateKind =
  | 'loading'
  | 'empty'
  | 'partial'
  | 'error'
  | 'blocked'
  | 'success'

export interface UiStateDescriptor {
  kind: UiStateKind
  title: string
  description: string
}

export function describeResultsWorkspaceState(input: {
  isRunning: boolean
  hasResults: boolean
  hasError: boolean
  hasBlocker: boolean
}): UiStateDescriptor {
  if (input.hasBlocker) {
    return {
      kind: 'blocked',
      title: 'Blocked state',
      description:
        'A blocker is active. Resolve it first, then continue the workflow.',
    }
  }
  if (input.hasError) {
    return {
      kind: 'error',
      title: 'Error state',
      description:
        'The last operation failed. Use diagnostics and retry guidance before rerunning.',
    }
  }
  if (input.isRunning && input.hasResults) {
    return {
      kind: 'partial',
      title: 'Partial state',
      description:
        'A run is currently in progress while previous results are still visible.',
    }
  }
  if (input.isRunning) {
    return {
      kind: 'loading',
      title: 'Loading state',
      description:
        'A run is in progress. Wait for completion before making comparisons.',
    }
  }
  if (!input.hasResults) {
    return {
      kind: 'empty',
      title: 'Empty state',
      description:
        'No result set is loaded yet. Start a run or load one from history.',
    }
  }
  return {
    kind: 'success',
    title: 'Success state',
    description:
      'Results are ready. Review score, cost, and evidence to decide next steps.',
  }
}
