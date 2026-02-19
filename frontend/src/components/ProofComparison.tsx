import type { RunMetrics } from '../types'

interface ComparisonCase {
  case_id: string
  label: string
  model_id: string
  scaffold_id: string
  score: number
  cost: number
  metrics?: RunMetrics
}

interface ProofComparisonProps {
  cases: ComparisonCase[]
  isLoading: boolean
}

function formatCost(usd: number): string {
  if (usd === 0) return '$0.000'
  if (usd < 0.001) return `<$0.001`
  return `$${usd.toFixed(3)}`
}

function formatQPD(qpd: number): string {
  if (!isFinite(qpd)) return '—'
  if (qpd >= 1000) return `${(qpd / 1000).toFixed(1)}k`
  return qpd.toFixed(1)
}

function formatDelta(delta: number, suffix: string = ''): string {
  const sign = delta >= 0 ? '+' : ''
  return `${sign}${delta.toFixed(2)}${suffix}`
}

function formatCostDelta(delta: number): string {
  const sign = delta >= 0 ? '+' : ''
  if (Math.abs(delta) < 0.001) return `${sign}0.000`
  return `${sign}${delta.toFixed(3)}`
}

function outcomeLabel(score: number): { text: string; cls: string } {
  if (score >= 80) return { text: 'PASS', cls: 'text-accent-winner bg-accent-winner/10 border-accent-winner/30' }
  if (score >= 50) return { text: 'WEAK', cls: 'text-accent-warning bg-accent-warning/10 border-accent-warning/30' }
  return { text: 'FAIL', cls: 'text-accent-loser bg-accent-loser/10 border-accent-loser/30' }
}

export default function ProofComparison({ cases, isLoading }: ProofComparisonProps) {
  if (isLoading) {
    return (
      <div className="bg-bg-secondary border border-border rounded-lg p-6 font-mono">
        <div className="text-xs text-text-secondary mb-4 tracking-widest">PROOF COMPARISON</div>
        <div className="text-text-secondary text-xs animate-pulse">Computing...</div>
      </div>
    )
  }

  if (cases.length === 0) {
    return (
      <div className="bg-bg-secondary border border-border rounded-lg p-6 font-mono">
        <div className="text-xs text-text-secondary mb-4 tracking-widest">PROOF COMPARISON</div>
        <div className="text-text-secondary text-xs opacity-40">No comparison data</div>
      </div>
    )
  }

  // Compute quality-per-dollar (score / cost*1000) for each case
  const qpdValues = cases.map((c) => {
    const costMillis = c.cost * 1000
    return costMillis > 0 ? c.score / costMillis : Infinity
  })

  const maxQpd = Math.max(...qpdValues.filter(isFinite))
  const bestQpdIndex = qpdValues.indexOf(maxQpd)

  // Deltas: case[1] vs case[0], case[2] vs case[0]
  const base = cases[0]
  const baseQpd = qpdValues[0]

  const rows = cases.map((c, i) => {
    const qpd = qpdValues[i]
    const isBest = i === bestQpdIndex && isFinite(qpd)

    let scoreDelta: number | null = null
    let costDelta: number | null = null
    let qpdDelta: number | null = null

    if (i > 0 && base) {
      scoreDelta = c.score - base.score
      costDelta = c.cost - base.cost
      qpdDelta = isFinite(qpd) && isFinite(baseQpd) ? qpd - baseQpd : null
    }

    const outcome = outcomeLabel(c.score)

    return { case: c, qpd, isBest, scoreDelta, costDelta, qpdDelta, outcome, index: i }
  })

  return (
    <div className="bg-bg-secondary border border-border rounded-lg p-6 font-mono">
      <div className="text-xs text-text-secondary mb-5 tracking-widest">PROOF COMPARISON</div>

      {/* Column headers */}
      <div className="grid grid-cols-[180px_1fr_1fr_80px_80px_90px_80px_80px_80px] gap-x-2 text-xs text-text-secondary/60 mb-2 tabular-nums">
        <span>CASE</span>
        <span>MODEL</span>
        <span>SCAFFOLD</span>
        <span className="text-right">SCORE</span>
        <span className="text-right">COST</span>
        <span className="text-right">QPD</span>
        <span className="text-right">Δ SCORE</span>
        <span className="text-right">Δ COST</span>
        <span className="text-right">OUTCOME</span>
      </div>

      <div className="border-t border-border/40 mb-1" />

      {rows.map(({ case: c, qpd, isBest, scoreDelta, costDelta, outcome, index }) => (
        <div
          key={c.case_id}
          className={[
            'grid grid-cols-[180px_1fr_1fr_80px_80px_90px_80px_80px_80px] gap-x-2 items-center py-2 text-xs tabular-nums',
            index < rows.length - 1 ? 'border-b border-border/20' : '',
            isBest ? 'bg-accent-winner/5 rounded' : '',
          ].join(' ')}
        >
          {/* Label */}
          <span className={['truncate', isBest ? 'text-accent-winner' : 'text-text-primary'].join(' ')}>
            {isBest && <span className="mr-1 text-accent-winner">*</span>}
            {c.label}
          </span>

          {/* Model */}
          <span className="text-text-secondary truncate">{c.model_id}</span>

          {/* Scaffold */}
          <span className="text-text-secondary truncate">{c.scaffold_id}</span>

          {/* Score */}
          <span
            className={[
              'text-right font-semibold',
              c.score >= 80
                ? 'text-accent-winner'
                : c.score >= 50
                  ? 'text-accent-warning'
                  : 'text-accent-loser',
            ].join(' ')}
          >
            {c.score.toFixed(1)}
          </span>

          {/* Cost */}
          <span className="text-right text-text-primary">{formatCost(c.cost)}</span>

          {/* Quality-per-dollar */}
          <span
            className={[
              'text-right',
              isBest ? 'text-accent-winner font-semibold' : 'text-text-secondary',
            ].join(' ')}
          >
            {formatQPD(qpd)}
          </span>

          {/* Delta Score */}
          <span
            className={[
              'text-right',
              scoreDelta === null
                ? 'text-text-secondary/30'
                : scoreDelta > 0
                  ? 'text-accent-winner'
                  : scoreDelta < 0
                    ? 'text-accent-loser'
                    : 'text-text-secondary',
            ].join(' ')}
          >
            {scoreDelta === null ? '—' : formatDelta(scoreDelta)}
          </span>

          {/* Delta Cost */}
          <span
            className={[
              'text-right',
              costDelta === null
                ? 'text-text-secondary/30'
                : costDelta > 0
                  ? 'text-accent-loser'
                  : costDelta < 0
                    ? 'text-accent-winner'
                    : 'text-text-secondary',
            ].join(' ')}
          >
            {costDelta === null ? '—' : formatCostDelta(costDelta)}
          </span>

          {/* Outcome */}
          <span
            className={[
              'text-right',
              'inline-flex justify-end',
            ].join(' ')}
          >
            <span
              className={[
                'text-xs font-bold border rounded px-1.5 py-0.5',
                outcome.cls,
              ].join(' ')}
            >
              {outcome.text}
            </span>
          </span>
        </div>
      ))}

      {/* Legend */}
      <div className="mt-4 pt-3 border-t border-border/40 flex gap-4 text-xs text-text-secondary/50">
        <span><span className="text-accent-winner">*</span> best quality-per-dollar</span>
        <span>QPD = score / (cost × 1000)</span>
        <span>Δ relative to case 1</span>
      </div>
    </div>
  )
}
