import { memo, useCallback, useMemo, useRef, useState } from 'react'

import type { RunResults } from '../types'

interface DiffViewProps {
  results: RunResults
  scaffoldNames: Record<string, string>
}

function uniqueLineSet(lines: string[]): Set<string> {
  return new Set(lines.map((line) => line.trim()).filter(Boolean))
}

function DiffView({ results, scaffoldNames }: DiffViewProps) {
  const scaffoldIds = Object.keys(results)
  const [leftId, setLeftId] = useState(scaffoldIds[0] ?? '')
  const [rightId, setRightId] = useState(scaffoldIds[1] ?? scaffoldIds[0] ?? '')
  const leftPaneRef = useRef<HTMLDivElement | null>(null)
  const rightPaneRef = useRef<HTMLDivElement | null>(null)
  const syncInFlightRef = useRef(false)

  const { leftLines, rightLines, rightSet, leftSet } = useMemo(() => {
    const leftOutput = results[leftId]?.output ?? ''
    const rightOutput = results[rightId]?.output ?? ''
    const leftLines = leftOutput.split('\n')
    const rightLines = rightOutput.split('\n')
    return {
      leftLines,
      rightLines,
      leftSet: uniqueLineSet(leftLines),
      rightSet: uniqueLineSet(rightLines),
    }
  }, [leftId, results, rightId])

  const syncScroll = useCallback(
    (source: HTMLDivElement | null, target: HTMLDivElement | null) => {
      if (!source || !target || syncInFlightRef.current) return
      syncInFlightRef.current = true
      target.scrollTop = source.scrollTop
      target.scrollLeft = source.scrollLeft
      requestAnimationFrame(() => {
        syncInFlightRef.current = false
      })
    },
    [],
  )

  if (scaffoldIds.length < 2) return null

  return (
    <section className="rounded-lg border border-border bg-bg-secondary p-4">
      <div className="mb-3 text-xs font-mono uppercase tracking-widest text-text-secondary">
        Output Diff
      </div>
      <div className="mb-3 flex flex-wrap gap-2 font-mono text-xs">
        <select
          aria-label="Left scaffold for diff"
          value={leftId}
          onChange={(e) => setLeftId(e.target.value)}
          className="rounded border border-border bg-bg-primary px-2 py-1"
        >
          {scaffoldIds.map((id) => (
            <option key={id} value={id}>
              {scaffoldNames[id] ?? id}
            </option>
          ))}
        </select>
        <span className="self-center text-text-secondary">vs</span>
        <select
          aria-label="Right scaffold for diff"
          value={rightId}
          onChange={(e) => setRightId(e.target.value)}
          className="rounded border border-border bg-bg-primary px-2 py-1"
        >
          {scaffoldIds.map((id) => (
            <option key={id} value={id}>
              {scaffoldNames[id] ?? id}
            </option>
          ))}
        </select>
      </div>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
        <div
          ref={leftPaneRef}
          onScroll={() => syncScroll(leftPaneRef.current, rightPaneRef.current)}
          className="max-h-96 overflow-auto rounded border border-border bg-bg-primary p-3 text-xs font-mono leading-relaxed touch-pan-x snap-x snap-mandatory"
        >
          {leftLines.map((line, idx) => (
            <div
              key={`${idx}-${line.slice(0, 10)}`}
              className={rightSet.has(line.trim()) ? '' : 'bg-accent-winner/10'}
            >
              {line}
            </div>
          ))}
        </div>
        <div
          ref={rightPaneRef}
          onScroll={() => syncScroll(rightPaneRef.current, leftPaneRef.current)}
          className="max-h-96 overflow-auto rounded border border-border bg-bg-primary p-3 text-xs font-mono leading-relaxed touch-pan-x snap-x snap-mandatory"
        >
          {rightLines.map((line, idx) => (
            <div
              key={`${idx}-${line.slice(0, 10)}`}
              className={leftSet.has(line.trim()) ? '' : 'bg-accent-loser/10'}
            >
              {line}
            </div>
          ))}
        </div>
      </div>
    </section>
  )
}

export default memo(DiffView)
