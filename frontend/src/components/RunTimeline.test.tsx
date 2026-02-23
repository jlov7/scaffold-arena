import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import RunTimeline from './RunTimeline'

describe('RunTimeline', () => {
  it('renders empty state when no events are available', () => {
    render(<RunTimeline events={[]} />)
    expect(
      screen.getByText(/No timeline available yet/i),
    ).toBeInTheDocument()
  })

  it('updates active event when selecting timeline rows', () => {
    const events = [
      {
        seq: 1,
        event: 'run_started',
        ts_ms: 1,
        scaffold_id: null,
        summary: 'Run started',
      },
      {
        seq: 2,
        event: 'scaffold_completed',
        ts_ms: 2,
        scaffold_id: 'bare',
        summary: 'bare completed',
      },
    ]

    render(<RunTimeline events={events} />)
    fireEvent.click(screen.getByRole('button', { name: /Run started/i }))
    expect(screen.getByText(/Event 1 of 2/i)).toBeInTheDocument()
  })
})
