import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import OnboardingChecklist from './OnboardingChecklist'

describe('OnboardingChecklist', () => {
  test('shows completion progress and next required action', () => {
    render(
      <OnboardingChecklist
        hasTask
        hasModel
        hasRun={false}
        hasResults={false}
        hasComparison={false}
      />,
    )

    expect(screen.getByText('2/5 complete')).toBeInTheDocument()
    expect(
      screen.getByText(/No guesswork: your next action is "Run the arena"/i),
    ).toBeInTheDocument()
  })

  test('shows completion guidance when all steps are done', () => {
    render(
      <OnboardingChecklist
        hasTask
        hasModel
        hasRun
        hasResults
        hasComparison
      />,
    )

    expect(
      screen.getByText(/You are fully through the core flow/i),
    ).toBeInTheDocument()
  })

  test('adapts review/proof copy for executive profile', () => {
    render(
      <OnboardingChecklist
        hasTask
        hasModel
        hasRun
        hasResults={false}
        hasComparison={false}
        profile="executive"
      />,
    )

    expect(
      screen.getByText(/Confirm winner confidence quickly/i),
    ).toBeInTheDocument()
    expect(screen.getByText(/Export and share concise proof/i)).toBeInTheDocument()
  })

  test('exposes hide control when callback is provided', () => {
    const onHide = vi.fn()
    render(
      <OnboardingChecklist
        hasTask={false}
        hasModel={false}
        hasRun={false}
        hasResults={false}
        hasComparison={false}
        onHide={onHide}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Hide' }))
    expect(onHide).toHaveBeenCalledTimes(1)
  })
})
