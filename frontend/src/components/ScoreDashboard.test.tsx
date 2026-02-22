import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ScoreDashboard } from './ScoreDashboard'
import type { RunResults } from '../types'

describe('ScoreDashboard', () => {
  it('renders safely when scaffolds have no evaluation payload', () => {
    const results = {
      bare: {
        output: '',
        error: 'provider auth failed',
      },
    } as unknown as RunResults

    render(
      <ScoreDashboard
        results={results}
        winnerId={null}
        onRunComparison={vi.fn()}
        onRunAutopsy={vi.fn()}
      />,
    )

    expect(screen.getByText(/Results/i)).toBeInTheDocument()
    expect(
      screen.getByRole('button', {
        name: /Run proof comparison for winning scaffold/i,
      }),
    ).toBeDisabled()
  })
})
