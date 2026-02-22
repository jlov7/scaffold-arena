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
    <section className="max-w-5xl" aria-label="Leaderboard">
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
