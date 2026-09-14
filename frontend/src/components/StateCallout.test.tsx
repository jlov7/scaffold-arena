import { fireEvent, render, screen } from '@testing-library/react'
import { vi } from 'vitest'

import StateCallout from './StateCallout'

describe('StateCallout', () => {
  test('renders action button when provided', () => {
    const onAction = vi.fn()
    render(
      <StateCallout
        kind="empty"
        title="Empty state"
        description="No results yet."
        actionLabel="Start run"
        onAction={onAction}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Start run' }))
    expect(onAction).toHaveBeenCalledTimes(1)
  })
})
