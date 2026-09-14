import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import BlockerGuideCard from './BlockerGuideCard'

describe('BlockerGuideCard', () => {
  it('renders blocker title and steps', () => {
    render(
      <BlockerGuideCard
        playbook={{
          task: 'extraction',
          blocker: 'failed',
          title: 'Extraction recovery playbook',
          summary: 'Clear the blocker and continue.',
          primaryAction: 'retry',
          steps: [
            { text: 'Retry now', action: 'retry' },
            { text: 'Verify required field coverage' },
          ],
        }}
        onPrimaryAction={() => {}}
        onOpenHelp={() => {}}
      />,
    )

    expect(screen.getByText(/Extraction recovery playbook/i)).toBeInTheDocument()
    expect(screen.getByText(/Verify required field coverage/i)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Retry now/i })).toBeInTheDocument()
  })

  it('routes primary action and help callbacks', () => {
    const onPrimaryAction = vi.fn()
    const onOpenHelp = vi.fn()
    render(
      <BlockerGuideCard
        playbook={{
          task: 'risk',
          blocker: 'auth',
          title: 'Risk recovery playbook',
          summary: 'Fix auth and continue.',
          primaryAction: 'open_settings',
          steps: [{ text: 'Open settings and configure token' }],
        }}
        onPrimaryAction={onPrimaryAction}
        onOpenHelp={onOpenHelp}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /Open settings now/i }))
    expect(onPrimaryAction).toHaveBeenCalledTimes(1)

    fireEvent.click(screen.getByRole('button', { name: /Open full help center/i }))
    expect(onOpenHelp).toHaveBeenCalledTimes(1)
  })
})
