import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { DecisionCanvas } from './DecisionCanvas'

describe('DecisionCanvas', () => {
  it('keeps Guided focused on one comparison decision with a truthful cost and adequacy preview', () => {
    const onNavigate = vi.fn()
    render(<DecisionCanvas job="compare" hasStudy={false} hasExperiment={false} hasExecution={false} onNavigate={onNavigate} />)

    expect(screen.getByRole('heading', { name: 'Compare' })).toBeInTheDocument()
    expect(screen.getByText(/Cost preview/)).toBeInTheDocument()
    expect(screen.getByText(/Adequacy preview/)).toBeInTheDocument()
    expect(screen.queryByText(/canonical JSON/i)).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Choose a study' }))
    expect(onNavigate).toHaveBeenCalledWith('studies')
  })

  it('explains a HOLD with its cause, consequence, and remediation', () => {
    render(<DecisionCanvas job="prove" hasStudy hasExperiment hasExecution hold={{ cause: 'No verified evidence receipt is selected.', consequence: 'A result cannot be promoted.', remediation: 'Open Evidence Room and verify a durable receipt.' }} onNavigate={vi.fn()} />)

    expect(screen.getByRole('alert')).toHaveTextContent('Cause')
    expect(screen.getByRole('alert')).toHaveTextContent('Consequence')
    expect(screen.getByRole('alert')).toHaveTextContent('Remediation')
  })
})
