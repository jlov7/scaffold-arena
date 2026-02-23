import { useEffect, useMemo, useState } from 'react'
import type { RunTimelineEvent } from '../types'

interface RunTimelineProps {
  events: RunTimelineEvent[]
}

function formatTime(tsMs: number): string {
  return new Date(tsMs).toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

export default function RunTimeline({ events }: RunTimelineProps) {
  const [activeIndex, setActiveIndex] = useState(0)
  const [isPlaying, setIsPlaying] = useState(false)
  const [speedMs, setSpeedMs] = useState(700)
  const maxIndex = Math.max(0, events.length - 1)
  const clampedIndex = Math.min(activeIndex, maxIndex)

  useEffect(() => {
    if (!isPlaying) return
    if (events.length <= 1) return
    if (clampedIndex >= maxIndex) return
    const timer = window.setTimeout(() => {
      setActiveIndex((prev) => Math.min(maxIndex, prev + 1))
    }, speedMs)
    return () => window.clearTimeout(timer)
  }, [clampedIndex, events.length, isPlaying, maxIndex, speedMs])

  const activeEvent = useMemo(
    () => events[clampedIndex] ?? null,
    [clampedIndex, events],
  )

  if (events.length === 0) {
    return (
      <div className="rounded border border-border/60 bg-bg-secondary p-3">
        <div className="text-[10px] uppercase tracking-widest text-text-muted">
          Timeline replay
        </div>
        <p className="mt-2 text-xs text-text-secondary">
          No timeline available yet. Run a benchmark or load a prior run from history.
        </p>
      </div>
    )
  }

  return (
    <section className="rounded border border-border/60 bg-bg-secondary p-3 font-mono">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <div className="text-[10px] uppercase tracking-widest text-text-muted">
            Timeline replay
          </div>
          <div className="mt-1 text-xs text-text-secondary">
            Step through run events to inspect sequence and failure timing.
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (isPlaying) {
                setIsPlaying(false)
                return
              }
              if (clampedIndex >= maxIndex) {
                setActiveIndex(0)
              }
              setIsPlaying(true)
            }}
            className="rounded border border-border px-2 py-1 text-[11px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            {isPlaying ? 'Pause' : 'Play'}
          </button>
          <button
            type="button"
            onClick={() => {
              setActiveIndex(0)
              setIsPlaying(false)
            }}
            className="rounded border border-border px-2 py-1 text-[11px] text-text-secondary hover:border-accent-info hover:text-accent-info"
          >
            Reset
          </button>
          <select
            value={String(speedMs)}
            onChange={(event) => setSpeedMs(Number(event.target.value))}
            className="rounded border border-border bg-bg-primary px-2 py-1 text-[11px] text-text-secondary"
            aria-label="Replay speed"
          >
            <option value="350">2x</option>
            <option value="700">1x</option>
            <option value="1200">0.5x</option>
          </select>
        </div>
      </div>

      <div className="mt-3 rounded border border-border bg-bg-primary p-3">
        {activeEvent ? (
          <>
            <div className="text-[11px] text-text-muted">
              Event {activeIndex + 1} of {events.length}
            </div>
            <div className="mt-1 text-xs text-text-primary">{activeEvent.summary}</div>
            <div className="mt-1 text-[11px] text-text-secondary">
              {activeEvent.event}
              {activeEvent.scaffold_id ? ` · ${activeEvent.scaffold_id}` : ''}
              {' · '}
              {formatTime(activeEvent.ts_ms)}
            </div>
          </>
        ) : (
          <div className="text-xs text-text-secondary">Timeline event unavailable.</div>
        )}
        <input
          type="range"
          min={0}
          max={maxIndex}
          value={clampedIndex}
          onChange={(event) => {
            setIsPlaying(false)
            setActiveIndex(Number(event.target.value))
          }}
          className="mt-3 w-full"
          aria-label="Timeline position"
        />
      </div>

      <div className="mt-3 max-h-52 overflow-y-auto rounded border border-border bg-bg-primary">
        {events.map((entry, index) => (
          <button
            key={`${entry.seq}-${entry.event}-${entry.ts_ms}`}
            type="button"
            onClick={() => {
              setIsPlaying(false)
              setActiveIndex(index)
            }}
            className={[
              'flex w-full items-center justify-between border-b border-border px-2 py-1 text-left text-[11px] last:border-b-0',
              index === clampedIndex
                ? 'bg-accent-info/10 text-accent-info'
                : 'text-text-secondary hover:bg-bg-tertiary',
            ].join(' ')}
          >
            <span className="truncate pr-2">{entry.summary}</span>
            <span className="shrink-0 tabular-nums text-[10px] text-text-muted">
              {formatTime(entry.ts_ms)}
            </span>
          </button>
        ))}
      </div>
    </section>
  )
}
