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
    <section className="max-w-5xl space-y-4" aria-label="Run history">
      <div className="lab-panel p-4">
        <div className="lab-label">Run archive</div>
        <p className="lab-copy mt-2 text-sm">
        Load any prior run to repopulate the arena results.
        </p>
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
