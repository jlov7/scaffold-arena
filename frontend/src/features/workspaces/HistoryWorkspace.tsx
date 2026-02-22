import { Suspense } from 'react'

import RunHistoryPanel from '../../components/RunHistoryPanel'
import type { ParsedRunRecord } from '../../lib/schema'

interface HistoryWorkspaceProps {
  runs: ParsedRunRecord[]
  onLoadRun: (runId: string) => void
  onStartFirstRun: () => void
}

export function HistoryWorkspace({
  runs,
  onLoadRun,
  onStartFirstRun,
}: HistoryWorkspaceProps) {
  return (
    <section className="max-w-5xl" aria-label="Run history">
      <div className="mb-4 text-xs font-mono text-text-secondary">
        Load any prior run to repopulate the arena results.
      </div>
      <Suspense fallback={<div className="text-xs text-text-muted">Loading history...</div>}>
        <RunHistoryPanel
          runs={runs}
          onLoadRun={onLoadRun}
          onStartFirstRun={onStartFirstRun}
        />
      </Suspense>
    </section>
  )
}
