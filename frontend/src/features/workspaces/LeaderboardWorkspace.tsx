import { Suspense } from 'react'

import LeaderboardPanel from '../../components/LeaderboardPanel'
import type { LeaderboardStats } from '../../types'

interface LeaderboardWorkspaceProps {
  stats: LeaderboardStats | null
  scaffoldNames: Record<string, string>
  onStartRun: () => void
}

export function LeaderboardWorkspace({
  stats,
  scaffoldNames,
  onStartRun,
}: LeaderboardWorkspaceProps) {
  return (
    <section className="max-w-5xl space-y-4" aria-label="Leaderboard">
      <div className="lab-panel p-4">
        <div className="lab-label">Scaffold performance</div>
        <p className="lab-copy mt-2 text-sm">
          Compare aggregate win rate, score, cost, and distribution patterns across stored runs.
        </p>
      </div>
      <Suspense fallback={<div className="text-xs text-text-muted">Loading leaderboard...</div>}>
        <LeaderboardPanel
          stats={stats}
          scaffoldNames={scaffoldNames}
          onStartRun={onStartRun}
        />
      </Suspense>
    </section>
  )
}
