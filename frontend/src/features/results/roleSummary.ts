import type { RunResults } from '../../types'
import type { UserProfile } from '../../components/journey/ExperienceModeCard'

export interface RoleResultsSummary {
  title: string
  body: string
  details: string[]
}

export function buildRoleResultsSummary(params: {
  results: RunResults | null
  winnerId: string | null
  scaffoldNames: Record<string, string>
  userProfile: UserProfile
}): RoleResultsSummary | null {
  const { results, winnerId, scaffoldNames, userProfile } = params
  if (!results) return null

  const ranked = Object.entries(results)
    .map(([scaffoldId, result]) => ({
      scaffoldId,
      score: result.evaluation?.total_score ?? 0,
      cost: result.metrics?.cost_usd ?? 0,
      timeMs: result.metrics?.wall_time_ms ?? 0,
    }))
    .sort((a, b) => b.score - a.score)

  if (ranked.length === 0) return null

  const winnerKey = winnerId && results[winnerId] ? winnerId : ranked[0].scaffoldId
  const winner = ranked.find((item) => item.scaffoldId === winnerKey) ?? ranked[0]
  const runnerUp = ranked.find((item) => item.scaffoldId !== winner.scaffoldId) ?? null
  const winnerName = scaffoldNames[winner.scaffoldId] ?? winner.scaffoldId
  const winnerCostPerPoint = winner.score > 0 ? winner.cost / winner.score : winner.cost
  const deltaScore = runnerUp ? winner.score - runnerUp.score : winner.score
  const deltaCost = runnerUp ? winner.cost - runnerUp.cost : winner.cost

  if (userProfile === 'executive') {
    return {
      title: 'Executive readout',
      body: `${winnerName} is the current recommendation.`,
      details: [
        `Confidence snapshot: score ${winner.score.toFixed(1)}.`,
        `Economics: $${winner.cost.toFixed(4)} total spend.`,
        `Decision speed: ${(winner.timeMs / 1000).toFixed(1)}s wall time.`,
      ],
    }
  }

  if (userProfile === 'operator') {
    return {
      title: 'Operator readout',
      body: `${winnerName} currently leads, but verify stability before rollout.`,
      details: [
        `Latency baseline: ${(winner.timeMs / 1000).toFixed(1)}s.`,
        `Cost per score point: $${winnerCostPerPoint.toFixed(4)}.`,
        `Runner-up score delta: ${deltaScore.toFixed(1)} points.`,
      ],
    }
  }

  if (userProfile === 'analyst') {
    return {
      title: 'Analyst readout',
      body: `${winnerName} has the strongest composite score in this run.`,
      details: [
        `Winner score: ${winner.score.toFixed(1)}.`,
        runnerUp
          ? `Score delta vs ${scaffoldNames[runnerUp.scaffoldId] ?? runnerUp.scaffoldId}: ${deltaScore.toFixed(1)}.`
          : 'No runner-up available in this run.',
        `Cost delta vs runner-up: $${deltaCost.toFixed(4)}.`,
      ],
    }
  }

  return {
    title: 'Evaluator readout',
    body: `${winnerName} leads. Confirm score, cost, and time together before finalizing.`,
    details: [
      `Winner score: ${winner.score.toFixed(1)}.`,
      `Winner cost: $${winner.cost.toFixed(4)}.`,
      `Winner runtime: ${(winner.timeMs / 1000).toFixed(1)}s.`,
    ],
  }
}
